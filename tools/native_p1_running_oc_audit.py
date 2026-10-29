#!/usr/bin/env python3
"""Strict Original Guest no-WFI simulated running current-SENSOR overrange.

The analogue 4095 ADC-like code is an EXTERNAL SIM_ONLY sensor fixture,
NOT the rotor plant's generated current or a board current measurement.
No guest IRQ/TZ/PWM writes. Do not qualify motor true overcurrent or board.
"""
import argparse
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p0_strict import parse_events,TraceError
from tools.native_dshot_scenario import load_native_scenario
from tools.native_p1_qualification import commands_for_scenario
from tools.native_p1_oc_fault_plan import load_oc_plan

EDGE=re.compile(r"E62_NATIVE_EXTERNAL_OC_EDGE vns=(\d+) frame=(\d+) "
                r"channel=(\d+) asserted=(\d+) code=(\d+) "
                r"trip=0x([0-9a-f]+) irq=0x([0-9a-f]+)")

def audit(events,run,plan,log):
    errors=[]
    edges=[tuple(int(x,16 if i>=5 else 10)
                 for i,x in enumerate(m.groups()))
           for m in EDGE.finditer(log)]
    cmds=[e for e in events if e["kind"]=="DSHOT"]
    scenario_count=run.get("configured_dshot_frames")
    if len(edges)!=2 or len(cmds)!=scenario_count or scenario_count!=3000:
        errors.append("OC_SOURCE_EDGES_OR_INDEPENDENT_DSHOT_COUNT_MISSING")
    else:
        for rec,frame,asserted in zip(edges,
                                      (plan["assert_frame"],plan["release_frame"]),
                                      (1,0)):
            ns,idx,ch,active,code,tz,irq=rec
            if (idx!=frame or active!=asserted or ch!=plan["channel"] or
                ns!=cmds[frame]["vns"]):
                errors.append("OC_SOURCE_NOT_QEMU_VIRTUAL_FRAME_ALIGNED")
        if edges[0][4]!=4095:
            errors.append("OC_SOURCE_4095_NOT_ACTUALLY_PUBLISHED")
        if not (edges[0][5]&0x40000 and edges[0][6]&4):
            errors.append("OC_SOURCE_COMPARATOR_OST3_AND_MCPWM_IRQ_NOT_REAL")
        if edges[1][3]!=0:
            errors.append("OC_SOURCE_NOT_RELEASED")
        if not any(e["kind"]=="PWM_PAIR" and
                   cmds[1500]["vns"]<=e["vns"]<edges[0][0] for e in events):
            errors.append("NO_ORIGINAL_MOTOR_RUNNING_BEFORE_OC_FAULT")
        if any(e["kind"]=="PWM_PAIR" and e["vns"]>edges[0][0]
               for e in events):
            errors.append("POWERED_COMMUTATION_AFTER_LATCHED_OC_FAULT")
    source=run.get("native_external_oc_sense_fault_plan") or {}
    if (source.get("sha256")!=plan["sha256"] or
        source.get("channel")!=plan["channel"] or
        source.get("scope")!="EXTERNAL_ADC_LIKE_SENSOR_OVERRANGE_NOT_PHYSICAL_MOTOR_CURRENT"):
        errors.append("EXTERNAL_OC_PLAN_HASH_OR_PROVENANCE_CHANGED")
    if (run.get("original_elf_sha256")!=
            "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0" or
        run.get("host_guest_register_writes") is not False or
        run.get("used_guest_wfi_or_gdb") is not False or
        run.get("synthetic_timed_bemf_enabled") is not False):
        errors.append("NOT_UNMODIFIED_ORIGINAL_NATIVE_NO_WFI")
    auto=run.get("autonomous_dshot") or {}
    if auto.get("sent")!=3000 or (
        run.get("original_guest_after") or {}).get("valid_frame_feeds",0)<1:
        errors.append("EXTERNAL_DSHOT_OR_ORIGINAL_CRC_NOT_CONTINUOUS")
    receiver=run.get("receiver_after") or {}
    if (not receiver.get("native_ost_latched",0)&0x40000 or
        not receiver.get("native_pwm_trip_latch",0)&0x40000):
        errors.append("OST3_LATCH_NOT_PERSISTENT_ON_ANALOG_RELEASE")
    motor=run.get("native_motor") or {}
    if motor.get("actual_pwm_six_bit_mask")!=0:
        errors.append("MOSFET_SIX_OUTPUTS_NOT_SAFE")
    if (run.get("pwm_source_after") or {}).get("running") is True:
        errors.append("PWM_CARRIER_STILL_RUNNING_AFTER_OC")
    return {
        "status":("PASS_P1_NATIVE_RUNNING_SIMULATED_OC_SENSE_OST3_SAFE_OFF"
                  if not errors else "FAIL_P1_NATIVE_RUNNING_OC_SENSE"),
        "qualified":not errors,
        "failures":list(dict.fromkeys(errors)),
        "source_phase":plan["phase"],
        "source_channel":plan["channel"],
        "source_edges":len(edges),
        "source_frames":len(cmds),
        "model_ost3_at_assertion":bool(edges and edges[0][5]&0x40000),
        "original_elf_and_no_wfi_protected":True,
        "final_ost3_latched":bool(receiver.get("native_ost_latched",0)&0x40000),
        "six_gate_outputs_off":motor.get("actual_pwm_six_bit_mask")==0,
        "classification":"SIM_ONLY_ADC_LIKE_OVERRANGE_NOT_PHYSICAL_MOTOR_CURRENT",
        "native_physical_motor_overcurrent_qualified":False,
        "real_board_protection_qualified":False,
        "automatic_rearm_qualified":False,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--scenario",type=Path,required=True)
    p.add_argument("--oc-fault-scenario",type=Path,required=True)
    p.add_argument("--evidence",type=Path,required=True)
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--qemu-log",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    try:
        stages,_=load_native_scenario(a.scenario)
        plan=load_oc_plan(a.oc_fault_scenario,stages)
        with a.events.open(errors="replace") as stream:
            ev=parse_events(stream)
        run=json.loads(a.evidence.read_text())
        result=audit(ev,run,plan,a.qemu_log.read_text(errors="replace"))
    except (OSError,ValueError,TypeError,KeyError,TraceError) as err:
        result={"status":"FAIL_P1_NATIVE_RUNNING_OC_SENSE",
                "qualified":False,"failures":[type(err).__name__+": "+str(err)],
                "real_board_protection_qualified":False}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("E62_NATIVE_P1_RUNNING_OC_SENSE "+json.dumps(result,sort_keys=True))
    return 0 if result["qualified"] else 1

if __name__=="__main__":
    raise SystemExit(main())
