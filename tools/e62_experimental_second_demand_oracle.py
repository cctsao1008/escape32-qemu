#!/usr/bin/env python3
"""E62 experimental SECOND powered-demand oracle, independent of aggregate P1.

This detects when first-start CAP1/TIMG12 counters hide a failed second
demand after a sustained neutral/coast. It does NOT claim standstill
restart or physical flight safety, never modifies Original P1 thresholds
and never synthesizes motor feedback.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Running as "python tools/<script>.py" places tools/, not repo root,
# on sys.path. Keep source imports stable in CI and standalone runs.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools.native_dshot_scenario import load_native_scenario
from tools.native_p1_qualification import commands_for_scenario
from tools.native_p0_strict import parse_events
from tools.native_motor_model_profiles import DATASHEET_PROFILES
import math

SHA_GUARD="ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN"
KIND_MIN=("PWM_PAIR","CAP1_ACK","TIMG12_ACK")
MIN_PER_DEMAND=12
COAST_SETTLE_NS=200_000_000
RPM_SIGN_THRESHOLD_MILLI=50_000
PROFILE_PATH=Path(__file__).resolve().parents[1]/"configs/e62-startup-second-demand-oracle-v1.json"

def load_oracle_profile(path=PROFILE_PATH, motor_profile="ecx87-kv147"):
    """Versioned negative qualification thresholds, never Guest rearm knobs."""
    d=json.loads(Path(path).read_text())
    required={"schema","scope","source_dshot_period_ns","source_tolerance_ns",
              "coast_settle_ms",
              "minimum_original_guest_events_per_powered_demand",
              "minimum_positive_rotor_samples_per_demand",
              "minimum_positive_rotor_span_ms",
              "minimum_positive_rotor_fraction",
              "maximum_significant_reverse_rotor_samples","profiles"}
    if (type(d) is not dict or set(d)!=required or
        d["schema"]!="e62.sim.startup-second-demand-oracle.v1" or
        d["scope"]!="SIM_ONLY_NEGATIVE_QUALIFICATION_NOT_GUEST_REARM" or
        d["source_dshot_period_ns"]!=1000000 or
        type(d["source_tolerance_ns"]) is not int or
        not 0<=d["source_tolerance_ns"]<=100 or
        type(d["coast_settle_ms"]) is not int or
        not 200<=d["coast_settle_ms"]<=250 or
        type(d["minimum_original_guest_events_per_powered_demand"]) is not int or
        not 12<=d["minimum_original_guest_events_per_powered_demand"]<=100 or
        type(d["minimum_positive_rotor_samples_per_demand"]) is not int or
        not 12<=d["minimum_positive_rotor_samples_per_demand"]<=100 or
        type(d["minimum_positive_rotor_span_ms"]) is not int or
        not 20<=d["minimum_positive_rotor_span_ms"]<=200 or
        type(d["minimum_positive_rotor_fraction"]) not in (int,float) or
        not math.isfinite(d["minimum_positive_rotor_fraction"]) or
        not 0.75<=d["minimum_positive_rotor_fraction"]<=1.0 or
        type(d["maximum_significant_reverse_rotor_samples"]) is not int or
        d["maximum_significant_reverse_rotor_samples"]!=0 or
        type(d["profiles"]) is not dict or
        set(d["profiles"])!=set(DATASHEET_PROFILES) or
        motor_profile not in d["profiles"]):
        raise ValueError("Unsafe or unsupported SIM_ONLY second-demand profile")
    for name,p in d["profiles"].items():
        if (type(p) is not dict or set(p)!={
            "positive_rpm_floor","significant_reverse_rpm_floor"} or
            any(type(p[k]) is not int or not 50<=p[k]<=300
                for k in p) or
            p["significant_reverse_rpm_floor"]!=p["positive_rpm_floor"]):
            raise ValueError("Unsafe motor-specific second-demand threshold: "+name)
    return d


def evaluate_second_demand(events,stages,profile=None,motor_profile="ecx87-kv147"):
    profile=profile if profile is not None else load_oracle_profile(motor_profile=motor_profile)
    motor=profile["profiles"][motor_profile]
    required=profile["minimum_original_guest_events_per_powered_demand"]
    positive_floor=1000*motor["positive_rpm_floor"]
    reverse_floor=1000*motor["significant_reverse_rpm_floor"]
    coast_settle_ns=profile["coast_settle_ms"]*1_000_000
    issues=[]
    if len(stages)!=5 or any(stage[0]<300 for stage in stages) or (
        [int(stage[1]) for stage in stages] != [0,200,0,200,0] or
        [int(stage[2]) for stage in stages] != [0,200,0,200,0] or
        any(stage[3]!=1 for stage in stages)
    ):
        return {"pass":False,"failures":["SECOND_DEMAND_FIXTURE_SCHEMA_UNEXPECTED"],
                "demand_windows":[],"coast":None}
    expected=list(commands_for_scenario(stages))
    source=[x for x in events if x["kind"]=="DSHOT"]
    if len(source)!=len(expected):
        issues.append("SECOND_DEMAND_DSHOT_FRAME_COUNT")
    mismatches=[]
    for i,(actual,want) in enumerate(zip(source,expected)):
        a=actual["data"]
        if a[:5]!=(i,want[0],want[1],0,0):
            mismatches.append(i)
            break
    if mismatches:
        issues.append("SECOND_DEMAND_DSHOT_SOURCE_MISMATCH")
    if len(source)==len(expected) and any(
        source[i]["vns"]<=source[i-1]["vns"] or
        (i>=2 and
         abs(source[i]["vns"]-source[i-1]["vns"]-
             profile["source_dshot_period_ns"])>profile["source_tolerance_ns"])
        for i in range(1,len(source))
    ):
        issues.append("SECOND_DEMAND_STALE_OR_DRIFTED_DSHOT_SOURCE_CLOCK")
    if issues:
        return {"pass":False,"failures":issues,
                "demand_windows":[],"coast":None}
    offsets=[0]
    for duration,*_ in stages:
        offsets.append(offsets[-1]+duration)
    if offsets[-1]!=len(source):
        return {"pass":False,"failures":["SECOND_DEMAND_SOURCE_BOUNDARY"],
                "demand_windows":[],"coast":None}
    boundaries=[source[i]["vns"] for i in offsets[:-1]]
    if boundaries!=sorted(boundaries):
        issues.append("SECOND_DEMAND_REORDERED_SOURCE_BOUNDARIES")
    demand_windows=[]
    for stage_idx in (1,3):
        start=boundaries[stage_idx]
        stop=boundaries[stage_idx+1]
        selected=[event for event in events if
                  start<=event["vns"]<stop]
        counts={kind:sum(e["kind"]==kind for e in selected)
                for kind in KIND_MIN}
        rotor=[e for e in selected if e["kind"]=="ROTOR"]
        rpms=[e["data"][0] for e in rotor]
        positive_times=[e["vns"] for e in rotor if e["data"][0]>=positive_floor]
        pos=len(positive_times)
        neg=sum(r<=-reverse_floor for r in rpms)
        positive_span_ns=(max(positive_times)-min(positive_times)
                          if positive_times else 0)
        if any(counts[kind]<required for kind in KIND_MIN):
            issues.append("SECOND_DEMAND_" +
                          ("FIRST" if stage_idx==1 else "REACQUISITION") +
                          "_GUEST_CLOSED_LOOP_NOT_PROVEN")
        if (pos<profile["minimum_positive_rotor_samples_per_demand"] or
            pos<profile["minimum_positive_rotor_fraction"]*len(rotor) or
            positive_span_ns<profile["minimum_positive_rotor_span_ms"]*1_000_000):
            issues.append("SECOND_DEMAND_" +
                          ("FIRST" if stage_idx==1 else "REACQUISITION") +
                          "_SUSTAINED_POSITIVE_ROTOR_RESPONSE_MISSING")
        if neg>profile["maximum_significant_reverse_rotor_samples"]:
            issues.append("SECOND_DEMAND_" +
                          ("FIRST" if stage_idx==1 else "REACQUISITION") +
                          "_SIGNIFICANT_REVERSE_ROTATION")
        demand_windows.append({
            "stage_index":stage_idx,"start_virtual_ns":start,
            "end_virtual_ns":stop,"source_counts":counts,
            "positive_rotor_samples_ge_50rpm":pos,
            "negative_rotor_samples_below_minus_floor":neg,
            "positive_rotor_observation_span_ms":positive_span_ns/1_000_000,
            "rotor_samples":len(rotor),
            "profile_positive_rpm_floor":motor["positive_rpm_floor"]
        })
    coast_start=boundaries[2]
    coast_end=boundaries[3]
    coast_events=[e for e in events if
                  coast_start+coast_settle_ns<=e["vns"]<coast_end]
    late_counts={k:sum(e["kind"]==k for e in coast_events)
                 for k in KIND_MIN}
    if any(late_counts.values()):
        issues.append("SECOND_DEMAND_COAST_UNEXPECTED_ACTIVE_COMMUTATION")
    coast={"start_virtual_ns":coast_start,"end_virtual_ns":coast_end,
           "settle_ms":profile["coast_settle_ms"],
           "late_guest_motor_event_counts":late_counts,
           "verified_complete_standstill":False}
    return {"pass":not issues,"failures":issues,
            "demand_windows":demand_windows,"coast":coast}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--scenario",type=Path,required=True)
    p.add_argument("--evidence",type=Path,required=True)
    p.add_argument("--strict-original-p1",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--sim-oracle-profile",type=Path,default=PROFILE_PATH)
    p.add_argument("--sim-motor-profile",choices=DATASHEET_PROFILES,
                   default="ecx87-kv147")
    a=p.parse_args()
    stages,meta=load_native_scenario(a.scenario)
    events=parse_events(a.events.read_text(errors="replace").splitlines())
    ev=json.loads(a.evidence.read_text())
    strict=json.loads(a.strict_original_p1.read_text())
    result=evaluate_second_demand(
        events,stages,load_oracle_profile(a.sim_oracle_profile,a.sim_motor_profile),
        a.sim_motor_profile)
    original_failures=strict.get("unwaived_observability_failures")
    provenance=(
        isinstance(original_failures,list) and
        SHA_GUARD in original_failures and
        ev.get("experimental_candidate_not_original") is True and
        ev.get("native_dshot_scenario",{}).get("sha256")==meta["sha256"] and
        ev.get("host_guest_register_writes") is False and
        ev.get("used_guest_wfi_or_gdb") is False and
        ev.get("synthetic_timed_bemf_enabled") is False and
        ev.get("original_elf_sha256")!=meta["original_elf_sha256"]
    )
    if not provenance:
        result["failures"].append("SECOND_DEMAND_PROVENANCE_OR_ORIGINAL_P1_GATE")
    strict_non_sha=(
        [x for x in original_failures if x!=SHA_GUARD]
        if isinstance(original_failures,list) else ["MISSING_STRICT_FAIL_LIST"])
    # Strict mechanical failures are NOT provenance faults and MUST still
    # keep the entire scenario red, even if the independent stage oracle
    # happens to have a different coverage of the same physical event.
    result["strict_original_p1_non_sha_failures"]=strict_non_sha
    result["pass"]=not result["failures"] and not strict_non_sha
    report={
        "schema":"e62.experimental.independent-second-demand.v1",
        "classification":"EXPERIMENTAL_ONLY_NOT_ORIGINAL_P1_OR_HARDWARE",
        "strict_original_p1_qualified":False,
        "hardware_qualified":False,
        "measured_standstill_restart":False,
        "source_scenario_sha256":meta["sha256"],
        "independent_demand_oracle":result,
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("E62_SECOND_DEMAND_ORACLE "+json.dumps({
        "pass":result["pass"],"failures":result["failures"],
        "strict_non_sha_failures":strict_non_sha,
        "windows":result["demand_windows"],"coast":result["coast"]},
        sort_keys=True),flush=True)
    return 0 if result["pass"] else 1


if __name__=="__main__":
    raise SystemExit(main())
