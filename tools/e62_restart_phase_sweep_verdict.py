#!/usr/bin/env python3
"""E62 #5 *actual-source* first/coast/second-demand SIM_ONLY motor verdict.

Uses Original Rel17.3 Guest, genuine native QEMU virtual-time events and
effective machine-property readback. Never controls the Guest and never
uses the QEMU model's internal angle to authorize startup/rearm.
The configured initial phase is a SIM experiment independent variable,
NOT a firmware rotor angle sensor. A negative rotor event is never waived.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_dshot_scenario import load_native_scenario
from tools.native_p1_qualification import analyze
from tools.e62_experimental_second_demand_oracle import (
    evaluate_second_demand, load_oracle_profile)
from tools.e62_restart_phase_torque_audit import read_events, diagnose
from tools.e62_sim_profile_contract import load as load_model_profile

ORIGINAL_SHA="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"


def evidence_errors(evidence,meta,profile,initial_degrees,study):
    errors=[]
    if (evidence.get("original_elf_sha256")!=ORIGINAL_SHA or
        evidence.get("experimental_candidate_not_original") is not False):
        errors.append("NOT_IMMUTABLE_ORIGINAL_REL17_GUEST")
    if (evidence.get("host_guest_register_writes") is not False or
        evidence.get("used_guest_wfi_or_gdb") is not False or
        evidence.get("synthetic_timed_bemf_enabled") is not False):
        errors.append("GUEST_REGISTER_WFI_OR_SYNTHETIC_BEMF_PROVENANCE")
    if (evidence.get("native_dshot_scenario") or {}).get("sha256")!=meta["sha256"]:
        errors.append("QEMU_EXTERNAL_FC_SCENARIO_SHA_CHANGED")
    if (evidence.get("configured_dshot_frames")!=meta["dshot_frames"] or
        (evidence.get("autonomous_dshot") or {}).get("sent")!=meta["dshot_frames"]):
        errors.append("QEMU_NATIVE_DSHOT_SOURCE_INCOMPLETE")
    if initial_degrees not in study["initial_electrical_degrees_grid"]:
        errors.append("INITIAL_ELECTRICAL_PHASE_NOT_IN_VERSIONED_GRID")
    effective=evidence.get("effective_sim_profile") or {}
    physical=(effective.get("effective_parameters") or {})
    if (effective.get("name")!=profile or
        effective.get("checked_against_named_model") is not True or
        physical.get("configured_initial_electrical_mdeg")!=initial_degrees*1000 or
        (evidence.get("motor_before") or {}).get(
            "effective_sim_motor_model")!=physical):
        errors.append("QEMU_INITIAL_PHASE_OR_MOTOR_EFFECTIVE_READBACK_MISMATCH")
    return errors


def qualify(evidence,events,stages,meta,profile,initial_degrees):
    cfg=load_model_profile()
    if profile not in cfg["profiles"]:
        raise ValueError("Unknown motor simulation profile")
    study=cfg["passive_reacquisition_study"]
    errors=evidence_errors(evidence,meta,profile,initial_degrees,study)
    original=analyze(events,evidence,stages,meta)
    second=evaluate_second_demand(
        events,stages,load_oracle_profile(motor_profile=profile),profile)
    # This source-only model-internal torque audit is diagnostic only.
    physical=diagnose(events,{
        "schema":"e62.native.dshot.v1","protocol":"DSHOT600",
        "frame_period_ns":1000000,"guest_ready_gating":False,
        "stages":[{"kind":"hold","duration_ms":s[0],"permille":s[1]}
                  for s in stages]})
    failures=list(errors)
    if not original["qualified"]:
        failures.extend("ORIGINAL_P1:"+x for x in
                        original["unwaived_observability_failures"])
    if not second["pass"]:
        failures.extend("SECOND_DEMAND:"+x for x in second["failures"])
    if (physical["first_20ms_negative_rpm_samples_le_minus50"] or
        physical["first_post_demand_model_torque_negative"]):
        failures.append("SOURCE_MODEL_RESTART_NEGATIVE_TORQUE_OR_REVERSE_RPM")
    return {
        "schema":"e62.sim.actual-source-initial-phase-restart.v1",
        "status":("PASS_SIM_ONLY_FIRST_AND_SECOND_DEMAND" if not failures else
                  "FAIL_SIM_ONLY_FIRST_OR_SECOND_DEMAND"),
        "qualified":not failures,
        "failures":list(dict.fromkeys(failures)),
        "motor_profile":profile,
        "initial_electrical_degrees":initial_degrees,
        "exact_external_dshot_frames":meta["dshot_frames"],
        "source_scenario_sha256":meta["sha256"],
        "original_p1_status":original["status"],
        "original_p1_failures":original["unwaived_observability_failures"],
        "independent_second_demand":second,
        "read_only_native_model_torque_diagnostic":physical,
        "model_internal_angle_is_not_guest_feedback":True,
        "automatic_rearm_granted":False,
        "original_rel17_p1_criteria_unchanged":True,
        "hardware_qualified":False,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--scenario",type=Path,required=True)
    p.add_argument("--evidence",type=Path,required=True)
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--motor-profile",required=True)
    p.add_argument("--initial-electrical-degrees",type=int,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    try:
        stages,meta=load_native_scenario(args.scenario)
        evidence=json.loads(args.evidence.read_text())
        result=qualify(evidence,read_events(args.events),stages,meta,
                       args.motor_profile,args.initial_electrical_degrees)
    except (ValueError,TypeError,KeyError,IndexError,RuntimeError,OSError) as exc:
        result={
            "schema":"e62.sim.actual-source-initial-phase-restart.v1",
            "status":"FAIL_SIM_ONLY_INVALID_SOURCE_EVIDENCE",
            "qualified":False,
            "failures":[type(exc).__name__+": "+str(exc)],
            "original_rel17_p1_criteria_unchanged":True,
            "model_internal_angle_is_not_guest_feedback":True,
            "automatic_rearm_granted":False,
        }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print("E62_SIM_INITIAL_PHASE_REAL_QEMU_VERDICT "+
          json.dumps(result,sort_keys=True),flush=True)
    return 0 if result["qualified"] else 1


if __name__=="__main__":
    raise SystemExit(main())
