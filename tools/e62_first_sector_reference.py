#!/usr/bin/env python3
"""E62 read-only first-sector independent electrical/mechanical cross-check.

Electrical oracle: reduced two-phase star R-LL-L-LL RL circuit driven from
the REAL QEMU six-pad SWITCH_FOCUS timestamps. Both high/low gate statuses,
off-state ideal diode clamps, and source rotor omega/theta are explicit.
The reduced circuit is ONLY valid while the floating U phase has |IU|~0.
Do not invent voltages or continue comparison when topology changes.

Mechanical oracle: independently recompute instantaneous torque from three
phase source currents/angle; reconcile QEMU integrated e*i energy against
motor kinetic energy and sampled viscous dissipation. This is a numerical
consistency test, not validation of a real motor at 75-150A.

Never inject rotor, PWM, BEMF, CAP1 or Guest state; never alter Original P1.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p0_strict import parse_events

ELF_SHA="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
KT=.0454
J=.00013
B=.0001
RLL=.0566
LLL=17.5e-6
DIODE=.7
OFFSETS=(0.,-2.*math.pi/3.,2.*math.pi/3.)


def trap(x):
    a=math.remainder(x,2*math.pi)
    sign=-1. if a<0. else 1.
    a=abs(a)
    if a<=math.pi/6.:return sign*6.*a/math.pi
    if a<=5.*math.pi/6.:return sign
    return sign*6.*(math.pi-a)/math.pi


def flux(wave,theta):
    if wave=="historical_sine":return math.sin(theta)
    if wave=="ideal_trapezoid":return trap(theta)
    raise ValueError("unknown exact waveform source")


def flux_coeff(wave):
    return KT/(math.sqrt(3.) if wave=="historical_sine" else 2.)


def line_voltage_for_mask(mask,current_a,vbus):
    """W-V terminal volts of idealized QEMU clamp assumption.

    Paired W positive and V negative, with U floating zero-current.
    The diode state is chosen by the polarity of the winding loop current.
    A deliberately UNKNOWN voltage at exactly zero current on both
    floating legs is invalid: refuse to make up a drive voltage.
    """
    if mask&~63:raise ValueError("invalid six-output mask")
    if mask & 3:raise ValueError("two-phase reference requires U disconnected")
    def terminal(hi_bit,lo_bit,phase_current):
        hi=bool(mask&(1<<hi_bit));lo=bool(mask&(1<<lo_bit))
        if hi and lo:raise ValueError("same-leg cross conduction")
        if hi:return vbus
        if lo:return 0.
        if phase_current>1e-9:return -DIODE
        if phase_current < -1e-9:return vbus+DIODE
        return None
    w=terminal(4,5,current_a)
    v=terminal(2,3,-current_a)
    return None if w is None or v is None else w-v


def linear_rotor_state(samples,t_ns):
    """Source ROTOR is sampled at 1ms; interpolate, do not pretend exact."""
    times=[r["vns"] for r in samples]
    ix=bisect.bisect_right(times,t_ns)
    if ix==0:return samples[0]["data"][0]*1e-3*2*math.pi/60.,samples[0]["data"][1]*1e-3
    if ix>=len(samples):return samples[-1]["data"][0]*1e-3*2*math.pi/60.,samples[-1]["data"][1]*1e-3
    a,b=samples[ix-1],samples[ix]
    w=(t_ns-a["vns"])/(b["vns"]-a["vns"])
    rpm=(a["data"][0]*(1-w)+b["data"][0]*w)*1e-3
    theta=(a["data"][1]*(1-w)+b["data"][1]*w)*1e-3
    return rpm*2*math.pi/60.,theta


def advance_two_phase(i,voltage,bemf,dt):
    """Independent exact solution to L_LL di/dt + R_LL i = V_LL - e_LL."""
    decay=math.exp(-RLL/LLL*dt)
    return i*decay+(voltage-bemf)*(1-decay)/RLL


def electrical_reference(focus,rotors,t0,tend,vbus,wave):
    changes=[e for e in focus if t0<=e["vns"]<=tend]
    before=[e for e in focus if e["vns"]<=t0]
    if not before:raise ValueError("first demand SWITCH_FOCUS source not covered")
    mask,gate=before[-1]["data"][:2]
    assert gate and mask==24, "First pair should be actual W-hi/V-lo"
    times=sorted(set([t0,tend]+[e["vns"] for e in changes]+
                     [r["vns"] for r in rotors if t0<=r["vns"]<=tend]))
    by_time={}
    for e in changes:by_time[e["vns"]]=e
    i=0.
    predicted={}
    on_s=off_s=other_s=unknown_s=0.
    for a,b in zip(times,times[1:]):
        if a in by_time:
            mask,gate=by_time[a]["data"][:2]
        dt=(b-a)*1e-9
        if not gate: mask=0
        voltage=line_voltage_for_mask(mask,i,vbus)
        # Off/off with zero loop current -> no drive; physically zero current
        # is valid there, but do NOT presume diode voltage if nonzero.
        if voltage is None:
            if abs(i)>1e-9:raise ValueError("unknown clamp with live current")
            voltage=0.
            unknown_s+=dt
        if mask==24:on_s+=dt
        elif mask==8:off_s+=dt
        else:other_s+=dt
        omega,theta=linear_rotor_state(rotors,(a+b)//2)
        k=flux_coeff(wave)
        ell=k*omega*(flux(wave,theta+OFFSETS[2])-
                      flux(wave,theta+OFFSETS[1]))
        i=advance_two_phase(i,voltage,ell,dt)
        predicted[b]=i
    records=[]
    for r in rotors:
        t=r["vns"]
        if t0<t<=tend:
            measured=r["data"][4]/1000.
            floating_u=r["data"][2]/1000.
            records.append({"since_pair_ms":round((t-t0)/1e6,4),
                            "i_w_a_observed":measured,
                            "i_w_a_independent":round(predicted[t],4),
                            "error_a":round(predicted[t]-measured,4),
                            "floating_u_a":floating_u})
    if not records:raise ValueError("no source ROTOR samples in electrical window")
    errs=[abs(e["error_a"]) for e in records]
    return {"assumption":"U open with IU=0; W/V RL loop; source rotor interpolation at 1ms",
            "phase_to_phase_R_ohm":RLL,"phase_to_phase_L_h":LLL,
            "switch_source_events":len(changes),"drive_full_on_fraction":on_s/(on_s+off_s+other_s),
            "v_low_w_open_fraction":off_s/(on_s+off_s+other_s),
            "other_mask_fraction":other_s/(on_s+off_s+other_s),
            "unknown_zero_current_voltage_fraction":unknown_s/(on_s+off_s+other_s),
            "replay_max_abs_current_error_a":max(errs),
            "replay_mean_abs_current_error_a":sum(errs)/len(errs),
            "observations":records}


def audit(events,evidence):
    assert evidence["original_elf_sha256"]==ELF_SHA
    assert evidence["host_guest_register_writes"] is False
    assert evidence["used_guest_wfi_or_gdb"] is False
    assert evidence["synthetic_timed_bemf_enabled"] is False
    assert evidence["pwm_source_before"]["effective_mcpwm_root_clock_hz"]==200000000
    wave=evidence["requested_sim_bemf_waveform"]
    assert evidence["motor_before"]["sim_bemf_waveform"]==wave
    obs=evidence["motor_before"]["effective_sim_motor_model"]
    assert obs["kv_rpm_per_v"]==210
    assert obs["terminal_kt_micro_nm_per_a"]==45400
    assert obs["phase_resistance_microohm"]==28300
    assert obs["phase_inductance_nanohenry"]==8750
    assert evidence["configured_dshot_frames"]==5100
    assert evidence["source_focus_window_ms"]=="1498:1520"
    vbus=obs["bus_millivolts"]/1000.
    dshot=[e for e in events if e["kind"]=="DSHOT"]
    assert len(dshot)==5100
    demand=next(e["vns"] for e in dshot if e["data"][1]==1 and e["data"][2]==448)
    pairs=[e for e in events if e["kind"]=="PWM_PAIR" and e["vns"]>demand]
    assert pairs[0]["data"][:2]==(8,24)
    t0=pairs[0]["vns"]
    tend=next(e["vns"] for e in pairs[1:] if e["data"][0]!=8)
    rotors=[e for e in events if e["kind"]=="ROTOR"]
    energies=[e for e in events if e["kind"]=="ENERGY"]
    first=[(r,en) for r,en in zip(rotors,energies) if t0<=r["vns"]<tend]
    if len(first)<5:raise ValueError("insufficient source rotor sample density")
    errs=[]
    k=flux_coeff(wave)
    for r,en in first:
        theta=r["data"][1]/1000.
        amp=[v/1000. for v in r["data"][2:5]]
        predicted=k*sum(i*flux(wave,theta+off) for i,off in zip(amp,OFFSETS))
        errs.append(predicted-r["data"][5]/1e6)
    e_work=0.;e_kin=0.;e_fric=0.
    for (a,ea),(b,eb) in zip(first,first[1:]):
        w0=a["data"][0]*.001*2*math.pi/60.
        w1=b["data"][0]*.001*2*math.pi/60.
        dt=(b["vns"]-a["vns"])*1e-9
        e_work+=(eb["data"][3]-ea["data"][3])/1e9
        e_kin+=.5*J*(w1*w1-w0*w0)
        e_fric+=B*(w0*w0+w1*w1)/2*dt
    focused=[e for e in events if e["kind"]=="SWITCH_FOCUS"]
    # This first ~5ms window uses only the independent two-phase
    # current loop. Outside it, third-phase diode conduction can occur.
    two_phase_end=min(t0+5_000_000,tend-1000)
    electrical=electrical_reference(focused,rotors,t0,two_phase_end,vbus,wave)
    if any(abs(e["floating_u_a"])>0.1 for e in electrical["observations"]):
        electrical["valid_two_phase_assumption"]=False
    else:
        electrical["valid_two_phase_assumption"]=True
    return {"scope":"SIM_ONLY_STATIC_RL_AND_KINEMATICS_NOT_HARDWARE",
            "waveform":wave,"bus_v":vbus,
            "initial_electrical_deg":obs["configured_initial_electrical_mdeg"]/1000.,
            "actual_switch_focus_count":len(focused),
            "first_pair_duration_ms":(tend-t0)/1e6,
            "first_pair_source_mask":pairs[0]["data"][1],
            "torque_independent_max_abs_error_nm":max(map(abs,errs)),
            "source_electromagnetic_work_j":e_work,
            "rotor_delta_kinetic_energy_j":e_kin,
            "rotor_viscous_dissipation_j":e_fric,
            "mechanical_energy_residual_j":e_work-e_kin-e_fric,
            "electrical_two_phase_reference":electrical,
            "guest_elf_sha256":ELF_SHA,
            "original_p1_unchanged":True,
            "hardware_calibrated":False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--evidence",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    d=audit(parse_events(a.events.read_text().splitlines()),
            json.loads(a.evidence.read_text()))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(d,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"waveform":d["waveform"],
        "initial_electrical_deg":d["initial_electrical_deg"],
        "actual_switch_focus_count":d["actual_switch_focus_count"],
        "first_pair_duration_ms":d["first_pair_duration_ms"],
        "torque_max_error_nm":d["torque_independent_max_abs_error_nm"],
        "electrical_current_mae_a":
        d["electrical_two_phase_reference"]["replay_mean_abs_current_error_a"],
        "electrical_valid":
        d["electrical_two_phase_reference"]["valid_two_phase_assumption"],
        "mech_energy_residual_j":d["mechanical_energy_residual_j"]},
        indent=2))


if __name__=="__main__":
    main()
