#!/usr/bin/env python3
"""Source-only, fail-closed E62 #5 CAP1 electrical-angle vs rotor-stop alias audit.

Consuming *actual* original QEMU P0 events: DShot, ROTOR, CMP_FILTER, CAP1,
T12_LOAD, PWM_PAIR. Never reads/writes Guest SRAM/MMIO or synthesizes BEMF.
1ms sampled ROTOR makes this a conservative diagnostic, NOT a rotor encoder,
firmware lock indicator, motor calibration, or Original P1 waiver.
"""
from __future__ import annotations
import argparse
import bisect
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_p0_strict import parse_events

ELF_SHA = "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
PHASE_OFFSETS = (0.0, -2.0*math.pi/3.0, 2.0*math.pi/3.0)
MATCH_WINDOW_NS = 750_000  # 0.75ms, source 1ms ROTOR interpolation
CAP_TO_TIMER_NS = 5_000

def crossings(rotors, phase=None):
    """Linear crossing times of rotor omega=0 or phase-flux(theta)=0."""
    result=[]
    for a,b in zip(rotors,rotors[1:]):
        if phase is None:
            v0=a["data"][0]/1000.0  # mechanical millirpm
            v1=b["data"][0]/1000.0
            levels=(0.0,)
        else:
            v0=a["data"][1]/1000.0 + PHASE_OFFSETS[phase]  # unwrapped mrad
            v1=b["data"][1]/1000.0 + PHASE_OFFSETS[phase]
            levels=tuple(k*math.pi for k in range(
                math.ceil(min(v0,v1)/math.pi),
                math.floor(max(v0,v1)/math.pi)+1))
        if v0==v1:continue
        for level in levels:
            if min(v0,v1)<=level<=max(v0,v1):
                f=(level-v0)/(v1-v0)
                result.append(round(a["vns"]+(b["vns"]-a["vns"])*f))
    return result

def nearest_distance(ns, candidates):
    return min((abs(ns-x) for x in candidates),default=None)

def state_at(rotors,ns):
    times=[r["vns"] for r in rotors]
    j=bisect.bisect_left(times,ns)
    if j==0 or j==len(times):return None
    a,b=rotors[j-1],rotors[j]
    f=(ns-a["vns"])/(b["vns"]-a["vns"])
    return {
        "rpm":round((a["data"][0]+f*(b["data"][0]-a["data"][0]))/1000.0,4),
        "electrical_deg_mod_360":round(math.degrees(
            (a["data"][1]+f*(b["data"][1]-a["data"][1]))/1000.0)%360.0,3),
        "source_sample_span_ns":b["vns"]-a["vns"]
    }

def classify_capture(cap, cmp_event, rotors, angle_crossings, speed_crossings, t12):
    phase=cmp_event["data"][0]
    if phase not in (0,1,2):raise ValueError("CAP1 comparator phase unsupported")
    if not 0<=cap["vns"]-cmp_event["vns"]<=1000:
        raise ValueError("CAP1 has no native CMP_FILTER edge")
    angle_delta=nearest_distance(cap["vns"],angle_crossings[phase])
    speed_delta=nearest_distance(cap["vns"],speed_crossings)
    near_angle=angle_delta is not None and angle_delta<=MATCH_WINDOW_NS
    near_speed=speed_delta is not None and speed_delta<=MATCH_WINDOW_NS
    cause=("ANGLE_ZERO_CANDIDATE" if near_angle and not near_speed else
           "SPEED_ZERO_ALIAS_CANDIDATE" if near_speed and not near_angle else
           "AMBIGUOUS_BOTH" if near_angle and near_speed else
           "UNRESOLVED")
    scheduled=any(0<=v["vns"]-cap["vns"]<=CAP_TO_TIMER_NS for v in t12)
    return {
        "cap1_vns":cap["vns"],"cmp_phase":phase,
        "cmp_level":cmp_event["data"][1],
        "angle_zero_distance_ms":(round(angle_delta/1e6,4)
                                  if angle_delta is not None else None),
        "speed_zero_distance_ms":(round(speed_delta/1e6,4)
                                  if speed_delta is not None else None),
        "model_state_at_capture":state_at(rotors,cap["vns"]),
        "classification":cause,
        "source_timg12_reloaded_within_5us":scheduled,
        "possible_false_commutation_reference":
            scheduled and cause!="ANGLE_ZERO_CANDIDATE"
    }

def audit(events, evidence, scenario):
    if evidence.get("original_elf_sha256")!=ELF_SHA:
        raise ValueError("Original ELF SHA mismatch")
    for field in ("host_guest_register_writes","used_guest_wfi_or_gdb",
                  "synthetic_timed_bemf_enabled"):
        if evidence.get(field) is not False:raise ValueError("Original source violated: "+field)
    if evidence.get("pwm_source_before",{}).get("effective_mcpwm_root_clock_hz")!=200_000_000:
        raise ValueError("MCPWM200 original source unavailable")
    dshot=[e for e in events if e["kind"]=="DSHOT"]
    expected=sum(x["duration_ms"] for x in scenario["stages"])
    if len(dshot)!=expected or evidence.get("configured_dshot_frames")!=expected:
        raise ValueError("DShot source count incorrect for pinned scenario")
    rotors=[e for e in events if e["kind"]=="ROTOR"]
    caps=[e for e in events if e["kind"]=="CAP1"]
    cmps=[e for e in events if e["kind"]=="CMP_FILTER"]
    t12=[e for e in events if e["kind"]=="T12_LOAD"]
    pairs=[e for e in events if e["kind"]=="PWM_PAIR"]
    if not all((rotors,caps,cmps,t12,pairs)):
        raise ValueError("missing native rotor/comparator/capture/timer/PWM source")
    speed_crossings=crossings(rotors)
    angle_crossings={p:crossings(rotors,p) for p in range(3)}
    cmp_times=[e["vns"] for e in cmps]
    starts=[];last_stage=None
    for e in dshot:
        stage=e["data"][1]
        if stage!=last_stage and stage in (1,3) and e["data"][2]>0:
            starts.append(e)
        last_stage=stage
    if len(starts)!=2:raise ValueError("source demands are not two positive stages")
    results=[]
    for start in starts:
        ns=start["vns"];last=ns+25_000_000
        pre=[r for r in rotors if r["vns"]<ns]
        active_pairs=[p for p in pairs if ns<=p["vns"]<last]
        if not pre:raise ValueError("missing pre-demand modeled rotor state")
        active_caps=[c for c in caps if ns<=c["vns"]<last]
        rows=[]
        for cap in active_caps:
            ix=bisect.bisect_right(cmp_times,cap["vns"])-1
            if ix<0:raise ValueError("CAP1 without CMP_FILTER")
            phase=cmps[ix]["data"][0]
            row=classify_capture(cap,cmps[ix],rotors,
                                 angle_crossings,speed_crossings,t12)
            row["relative_to_demand_ms"]=round((cap["vns"]-ns)/1e6,4)
            rows.append(row)
        possible_false=[r for r in rows if r["possible_false_commutation_reference"]]
        results.append({
            "source_dshot_stage":start["data"][1],
            "actual_pre_demand_model_rpm":pre[-1]["data"][0]/1000.0,
            "actual_pre_demand_model_electrical_rad":pre[-1]["data"][1]/1000.0,
            "first_25ms_source_pwm_pairs":len(active_pairs),
            "first_25ms_captures":rows,
            "scheduled_non_geometric_or_ambiguous_captures":len(possible_false),
            "reacquisition_safety_decision":(
                "REJECT_POSSIBLE_FALSE_BEMF_LOCK" if possible_false
                else "NOT_PROVEN_REACQUIRED")
        })
    return {
        "scope":"SIM_ONLY_SOURCE_DIAGNOSTIC_NOT_ORIGINAL_P1_OR_HARDWARE",
        "original_guest_sha256":ELF_SHA,
        "dshot_frames":len(dshot),
        "model_bemf_identity":"phase BEMF=Ke*omega*f(theta+phase)",
        "angle_matching_resolution":"1ms ROTOR interpolation, 0.75ms window",
        "captures_do_not_imply_geometric_commutation":True,
        "results":results,
        "original_p1_policy_unchanged":True,
        "issue5_reacquisition_qualified":False
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--evidence",type=Path,required=True)
    p.add_argument("--scenario",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    result=audit(parse_events(args.events.read_text().splitlines()),
                 json.loads(args.evidence.read_text()),
                 json.loads(args.scenario.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    for stage in result["results"]:
        print("ISSUE5_SOURCE_STAGE",stage["source_dshot_stage"],
              "pre_rpm",stage["actual_pre_demand_model_rpm"],
              "CAP1",[(r["relative_to_demand_ms"],r["classification"],
                       r["source_timg12_reloaded_within_5us"])
                      for r in stage["first_25ms_captures"]],
              "status",stage["reacquisition_safety_decision"])

if __name__=="__main__":
    main()
