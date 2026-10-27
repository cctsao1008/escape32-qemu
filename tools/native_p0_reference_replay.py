#!/usr/bin/env python3
"""Independent frozen *actual six-pad QEMU switch* replay of initial 90ms.

This explicitly does NOT advance Guest, rewrite Guest PWM/CAP1 or forge BEMF.
Original-source event timestamps are re-applied to the existing Python
current-continuous active-set reference. Compare source-native 1us
numerics with 1, 0.5, 0.25us frozen-input integrations.
"""
import argparse
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p0_strict import parse_events, TraceError
from tools.current_continuous_bldc import CurrentContinuousBLDC, LegTopology
from tools.native_motor_model_profiles import native_motor_parameters

WINDOW_NS=90_000_000


def decode_six_pad(mask,gate):
    if type(mask) is not int or mask<0 or mask>0x3f:
        raise ValueError("Invalid six-pad mask")
    if gate not in (0,1):
        raise ValueError("Invalid source gate")
    topology=[]
    for k in range(3):
        bits=(mask>>(2*k))&3
        if bits==3 and gate:
            raise ValueError("Unsafe concurrent high/low switching")
        topology.append("H" if gate and bits==1 else
                        "L" if gate and bits==2 else "Z")
    return LegTopology(tuple(topology))


def _phase_error(a,b):
    return abs(math.remainder(a-b,2*math.pi))


def _simulate(events,dt_ns, *, horizon_ns=WINDOW_NS):
    sw=[e for e in events if e["kind"]=="SWITCH"]
    if len(sw)<2:
        raise TraceError("Missing source-owned 120ms switch waveform")
    t0=sw[0]["vns"];end=t0+horizon_ns
    if sw[-1]["vns"]<end:
        raise TraceError("Native source switch window shorter than required")
    stream=[e for e in events if e["kind"] in ("SWITCH","ROTOR") and
            t0<=e["vns"]<=end]
    model=CurrentContinuousBLDC(
        native_motor_parameters("ecx87-kv147"),
        initial_electrical_rad=-math.pi/6,diode_forward_v=0.7)
    now=t0;tick=t0+1000;match=[]
    for e in stream:
        t=e["vns"]
        while tick<t:
            delta=tick-now
            if delta>0:
                # Physical QEMU schedules exactly one 1us plant callback,
                # plus shorter intervals at real PWM switching instants.
                remain=delta
                while remain:
                    h=min(remain,dt_ns)
                    model.advance(h*1e-9)
                    remain-=h
                now=tick
            tick+=1000
        if t>now:
            remain=t-now
            while remain:
                h=min(remain,dt_ns)
                model.advance(h*1e-9)
                remain-=h
            now=t
        if tick==t:
            tick+=1000
        if e["kind"]=="SWITCH":
            model.set_switches(decode_six_pad(e["data"][0],
                                               e["data"][1]))
        else:
            obs=e["data"]
            snap=model.sample(gate_enabled=any(
                leg!="Z" for leg in model.topology.legs))
            # Native trace electrical theta is intentionally UNWRAPPED,
            # host model wraps mechanical angle; compare modulo 2pi.
            theta_actual=obs[1]/1000
            currents=(obs[2]/1000,obs[3]/1000,obs[4]/1000)
            match.append({
                "t_ns":t,
                "rpm_err":abs(snap.mechanical_rpm-obs[0]/1000),
                "angle_err":_phase_error(snap.electrical_rad,theta_actual),
                "current_err":max(abs(a-b) for a,b in
                                  zip(snap.phase_currents_a,currents)),
            })
    if len(match)<10:
        raise TraceError("No rotor-state comparison samples in switch replay")
    last=model.sample(gate_enabled=any(leg!="Z" for leg in model.topology.legs))
    return {
        "dt_ns":dt_ns,"source_replay_window_ns":horizon_ns,
        "source_switch_events":len([e for e in stream if e["kind"]=="SWITCH"]),
        "rotor_comparison_samples":len(match),
        "max_abs_rpm_error":max(x["rpm_err"] for x in match),
        "max_abs_angle_error_rad":max(x["angle_err"] for x in match),
        "max_abs_current_error_a":max(x["current_err"] for x in match),
        "final_rpm":last.mechanical_rpm,
        "final_iabc_a":tuple(last.phase_currents_a),
        "final_angle_rad":last.electrical_rad,
        "reference_energy":model.diagnostics(),
    }


def compare(events):
    a,b,c=(_simulate(events,dt) for dt in (1000,500,250))
    coarse_diff=abs(a["final_rpm"]-b["final_rpm"])+sum(
        abs(x-y) for x,y in zip(a["final_iabc_a"],b["final_iabc_a"]))
    fine_diff=abs(b["final_rpm"]-c["final_rpm"])+sum(
        abs(x-y) for x,y in zip(b["final_iabc_a"],c["final_iabc_a"]))
    failures=[]
    if (a["max_abs_rpm_error"]>2.0 or
        a["max_abs_current_error_a"]>0.5 or
        a["max_abs_angle_error_rad"]>0.1):
        failures.append("QEMU_CPP_VS_INDEPENDENT_PYTHON_DISAGREEMENT")
    if not (fine_diff<coarse_diff or (fine_diff<1e-8 and coarse_diff<1e-8)):
        failures.append("HALVED_TIMESTEP_NOT_CONVERGENT")
    for model in (a,b,c):
        d=model["reference_energy"]
        if d["forced_current_projection_impulse_energy_j"]!=0:
            failures.append("REFERENCE_FORCED_SWITCH_CURRENT_PROJECTION")
    return {
        "status":"PASS_FROZEN_SWITCH_PHYSICS" if not failures else
                 "FAIL_FROZEN_SWITCH_PHYSICS",
        "qualified":not failures,
        "failures":failures,
        "model":"ECX87_KV147_SIM_ONLY",
        "host_guest_register_writes":False,
        "native_guest_execution_replayed":False,
        "switch_source":"ACTUAL_QEMU_AQ_DB_SIX_PAD_IN_VIRTUAL_TIME",
        "comparison":{key:a[key] for key in (
            "source_switch_events","rotor_comparison_samples",
            "max_abs_rpm_error","max_abs_angle_error_rad",
            "max_abs_current_error_a")},
        "convergence":{"coarse_to_half":coarse_diff,
                       "half_to_quarter":fine_diff,
                       "steps_ns":[1000,500,250]},
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--events",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    try:
        with a.events.open(errors="replace") as f:
            result=compare(parse_events(f))
    except (TraceError,ValueError,FloatingPointError,AssertionError,OSError,KeyError,TypeError) as exc:
        result={"status":"FAIL_FROZEN_SWITCH_PHYSICS","qualified":False,
                "failures":[type(exc).__name__+": "+str(exc)]}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("E62_P0_CURRENT_CONTINUOUS_REPLAY "+json.dumps(result,sort_keys=True))
    if not result["qualified"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
