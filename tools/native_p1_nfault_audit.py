#!/usr/bin/env python3
"""Strict no-WFI original-Guest external PA22 nFAULT negative acceptance.

A virtual-clocked external pin transition is NOT a Guest IRQ/TZ write.
Check exact frame source, genuine OST2 and safe-off; no automatic
motor-recovery/armed-return PASS is claimed after physical release.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p0_strict import parse_events, TraceError
from tools.native_dshot_scenario import load_native_scenario
from tools.native_p1_fault_plan import load_fault_plan


def audit(events,run,plan):
    fail=[]
    edges=[e for e in events if e["kind"]=="NFAULT_EDGE"]
    commands=[e for e in events if e["kind"]=="DSHOT"]
    if (len(edges)!=2 or len(commands)!=run.get(
            "configured_dshot_frames",0)):
        fail.append("MISSING_PHYSICAL_EDGE_OR_CONTINUOUS_SOURCE_FRAMES")
    else:
        for edge,idx,asserted in zip(
                edges,(plan["assert_frame"],plan["release_frame"]),(1,0)):
            if (edge["data"][0]!=asserted or
                edge["data"][1]!=idx or
                edge["vns"]!=commands[idx]["vns"]):
                fail.append("EXTERNAL_PA22_FAULT_NOT_ON_VIRTUAL_FRAME")
        if not edges[0]["data"][2]&0x20000:
            fail.append("OST2_NOT_SOURCE_LATCHED_ON_ACTUAL_NFAULT")
        if not edges[0]["data"][3]&4:
            fail.append("GENUINE_MCPWM4_FAULT_IRQ_NOT_PENDING")
        if any(e["kind"]=="PWM_PAIR" and e["vns"]>edges[0]["vns"]
               for e in events):
            fail.append("MOTOR_COMMUTATION_CONTINUED_AFTER_PHYSICAL_TRIP")
    source=run.get("native_external_fault_plan") or {}
    if source.get("sha256")!=plan["sha256"]:
        fail.append("EXTERNAL_FAULT_PLAN_HASH_CHANGED")
    if run.get("host_guest_register_writes") is not False or (
        run.get("used_guest_wfi_or_gdb") is not False or
        run.get("synthetic_timed_bemf_enabled") is not False):
        fail.append("SOURCE_NOT_NATURAL_NO_WFI_GUEST")
    if ((run.get("autonomous_dshot") or {}).get("sent") !=
        run.get("configured_dshot_frames") or
        (run.get("original_guest_after") or {}).get(
            "valid_frame_feeds",0)==0):
        fail.append("DASHOT_DID_NOT_CONTINUE_AND_GUEST_CRC_NOT_PROVEN")
    receiver=run.get("receiver_after") or {}
    ost=receiver.get("native_ost_latched",0)
    trip=receiver.get("native_pwm_trip_latch",0)
    if not ost&0x20000 or not trip&0x20000:
        fail.append("PHYSICAL_FAULT_LATCH_NOT_PERSISTENT_AT_END")
    if (run.get("native_motor") or {}).get("actual_pwm_six_bit_mask",64)!=0:
        fail.append("SIX_MOSFET_GATE_OUTPUT_NONZERO_AFTER_TRIP")
    # Guest may remain deliberately in non-returning shutdown, this
    # is NOT a clean restart. Require no spontaneous re-arm.
    if (run.get("pwm_source_after") or {}).get("running") is True:
        fail.append("PWM_CARRIER_STILL_RUNNING_AT_FAULT_CASE_END")
    result={
        "status":"PASS_P1_NATIVE_IN_FLIGHT_NFAULT_SAFE_OFF" if not fail
                 else "FAIL_P1_NATIVE_IN_FLIGHT_NFAULT_SAFE_OFF",
        "qualified":not fail,
        "failures":list(dict.fromkeys(fail)),
        "source_fault_edges":len(edges),
        "fault_assert_at_virtual_frame":plan["assert_frame"],
        "fault_release_at_virtual_frame":plan["release_frame"],
        "source_latched_ost2_at_fault":bool(edges and edges[0]["data"][2]&0x20000),
        "original_guest_never_halted_or_injected":True,
        "external_DShot_continuity":len(commands),
        "final_OST2_latched":bool(ost&0x20000),
        "final_gate_off":(run.get("native_motor") or {}).get(
            "actual_pwm_six_bit_mask")==0,
        "original_guest_crc_feeds":(run.get("original_guest_after") or {}).get(
            "valid_frame_feeds"),
        "scope":"SIM_ONLY_NFAULT_NEGATIVE_FAULT_RELEASE_NOT_RECOVERY",
        "automatic_rearm_and_flight_recovery_qualified":False,
        "electrical_hardware_qualified":False,
    }
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--scenario",type=Path,required=True)
    p.add_argument("--fault-scenario",type=Path,required=True)
    p.add_argument("--evidence",type=Path,required=True)
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    try:
        stages,_=load_native_scenario(a.scenario)
        plan=load_fault_plan(a.fault_scenario,stages)
        d=json.loads(a.evidence.read_text())
        with a.events.open(errors="replace") as f:
            result=audit(parse_events(f),d,plan)
    except (OSError,ValueError,TypeError,TraceError,KeyError) as exc:
        result={"status":"FAIL_P1_NATIVE_IN_FLIGHT_NFAULT_SAFE_OFF",
                "qualified":False,
                "failures":[type(exc).__name__+": "+str(exc)],
                "automatic_rearm_and_flight_recovery_qualified":False}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("E62_NATIVE_P1_NFAULT "+json.dumps(result,sort_keys=True))
    if not result["qualified"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
