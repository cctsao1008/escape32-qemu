#!/usr/bin/env python3
"""E62 FW porting: read-only original Guest CAP1 MMIO -> TIMG12 -> PWM trace.

No assumptions that IRQ ACK means an accepted BEMF event. Only an observed
Guest one-shot MMIO START after a CAP1 read counts as timer-arming evidence.
QEMU_CLOCK_VIRTUAL source events are the only clock. This is not a model,
motor/propeller qualification, or replacement for strict P0/P1.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.native_p0_strict import parse_events

CASE_NAMES=("smoke","gentle","direct20","steps")
PINNED_ELF="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
NEW_KINDS=("ECAP1_CAP1_READ","T12_LOAD","T12_START","T12_STOP")
TIMER_ZERO="TIMG12"
NSEC_PER_SEC=1_000_000_000

def indexed_after(events, kind, t, end=None):
    return [e for e in events if e["kind"]==kind and e["vns"]>=t and
            (end is None or e["vns"]<end)]

def compact(ev, anchor):
    if ev is None:
        return None
    return {"seq":ev["seq"],"ms_after_first_power":
            round((ev["vns"]-anchor)/1e6,6),
            "virtual_ns":ev["vns"],"source_data":list(ev["data"])}

def first_in_period(events, kind, start, stop):
    return next(iter(indexed_after(events,kind,start,stop)),None)

def timer_deadline_from_actual_start(start):
    a,b,c,d,e,_=start["data"]
    if b<=0 or a<0 or c<0:
        raise ValueError("invalid TIMG12 clock/start count")
    if d & 0x20:  # genuine QEMU count-up
        ticks=a+1-c
    else:
        ticks=c+1
    if ticks<=0:
        raise ValueError("invalid TIMG12 remaining ticks")
    duration=(ticks*NSEC_PER_SEC+b-1)//b
    return start["vns"]+duration, ticks

def audit(events, verdict, name):
    if name not in CASE_NAMES:
        raise ValueError("unknown P1 case")
    if verdict.get("status") not in (
        "PASS_P1_SIM_ONLY_OBSERVABILITY",
        "FAIL_P1_SIM_ONLY_OBSERVABILITY"):
        raise ValueError("missing pinned original P1 verdict")
    if not isinstance(verdict.get("qualified"),bool):
        raise ValueError("missing P1 qualified flag")
    if verdict.get("original_elf_sha256") not in (None,PINNED_ELF):
        raise ValueError("mismatching original ELF")
    onset=next((e for e in events if e["kind"]=="DSHOT" and
                e["data"][2]>0),None)
    if onset is None:
        raise ValueError("missing positive original DShot")
    first_pair=first_in_period(events,"PWM_PAIR",onset["vns"],None)
    if first_pair is None:
        raise ValueError("missing original physical PWM_PAIR")
    origin=first_pair["vns"]
    first_zero=first_in_period(events,TIMER_ZERO,origin,None)
    if first_zero is None:
        raise ValueError("missing original TIMG12 ZERO")
    caps=indexed_after(events,"CAP1",origin,first_zero["vns"])
    if not caps:
        raise ValueError("missing physical CAP1 before first TIMG12")
    if not any(e["kind"]=="ECAP1_CAP1_READ" for e in events):
        raise ValueError("missing original Guest CAP1 MMIO read event")
    if not any(e["kind"]=="T12_START" for e in events):
        raise ValueError("missing original Guest TIMG12 one-shot START")
    if not any(e["kind"]=="T12_LOAD" for e in events):
        raise ValueError("missing original Guest TIMG12 period load")
    caps_out=[]
    faults=[]
    for i,cap in enumerate(caps):
        deadline=caps[i+1]["vns"] if i+1<len(caps) else first_zero["vns"]
        acknowledgements=indexed_after(events,"CAP1_ACK",cap["vns"],deadline)
        ack=next((e for e in acknowledgements
                  if e["data"][2]==cap["data"][0]),None)
        reads=indexed_after(events,"ECAP1_CAP1_READ",cap["vns"],deadline)
        read=next((e for e in reads if e["data"][0]==cap["data"][0]),None)
        if not ack:
            faults.append("CAP1_NO_MATCHING_GUEST_ACK")
        if not read:
            faults.append("CAP1_NO_MATCHING_GUEST_READ")
        if ack and read and read["vns"]<ack["vns"]:
            # The specific pinned AM13E ISR clears the native CEVT1 first,
            # then reads CAP1 timestamp. Do not assume cross-port order.
            faults.append("CAP1_READ_PRECEDES_PINNED_ISR_ACK")
        if ack and read:
            # No control-flow guess: record concrete timer MMIO after read.
            st=indexed_after(events,"T12_START",read["vns"],deadline)
            starts=[e for e in st if e["vns"]<=first_zero["vns"]]
        else:
            starts=[]
        arm=starts[0] if starts else None
        load=first_in_period(events,"T12_LOAD",
                             read["vns"] if read else cap["vns"],
                             (arm["vns"]+1) if arm else deadline)
        if arm is not None and load is None:
            faults.append("GUEST_TIMER_STARTED_WITHOUT_POST_CAPTURE_PERIOD_LOAD")
        caps_out.append({
            "cap1":compact(cap,origin),
            "guest_cap1_ack":compact(ack,origin),
            "guest_cap1_mmio_read":compact(read,origin),
            "guest_timer_load_after_read":compact(load,origin),
            "guest_timer_start_after_read":compact(arm,origin),
            "mmio_observation":("GUEST_REARMED_TIMG12" if arm else
                                "NO_TIMG12_REARM_BETWEEN_CAPTURES"),
            "firmware_accept_reject_return_value_observed":False,
        })
    # Match latest actual start to a real silicon ZERO. No timer spoofing.
    before_zero=[e for e in events if e["vns"]<=first_zero["vns"]]
    arms=[e for e in before_zero if e["kind"]=="T12_START"]
    latest_start=arms[-1] if arms else None
    predicted_deadline=None
    tick_count=None
    error_ns=None
    if latest_start is not None:
        predicted_deadline,tick_count=timer_deadline_from_actual_start(latest_start)
        error_ns=first_zero["vns"]-predicted_deadline
        if abs(error_ns)>20:
            faults.append("NATIVE_TIMG12_ZERO_MISMATCHES_GUEST_ARMED_PERIOD")
        stops=[e for e in before_zero if e["kind"]=="T12_STOP"
               and e["vns"]>latest_start["vns"]]
        if stops:
            faults.append("NATIVE_TIMG12_ZERO_AFTER_GUEST_STOP")
    else:
        faults.append("NO_OBSERVED_TIMER_START_PRECEDING_ZERO")
    zero_ack=first_in_period(events,"TIMG12_ACK",first_zero["vns"],None)
    if zero_ack is None:
        faults.append("NO_GUEST_TIMG12_ZERO_ACK")
    later_pair=first_in_period(events,"PWM_PAIR",first_zero["vns"]+1,None)
    if later_pair is None:
        faults.append("NO_PHYSICAL_PWM_PAIR_AFTER_TIMER_ZERO")
    if latest_start and latest_start["data"][1]!=100_000_000:
        # Only declared AM13E 100MHz native timer assumed here.
        faults.append("TIMG12_BUS_CLOCK_CONTRACT_NOT_100MHZ")
    # Retain original source verdict. Diagnostic PASS is not P1 PASS.
    result={
        "case":name,"scope":"SOURCE_MMIO_PORTING_DIAGNOSTIC_ONLY",
        "p1_unchanged_original_verdict":verdict["status"],
        "p1_unchanged_qualified":verdict["qualified"],
        "first_power":compact(first_pair,origin),
        "first_timg12_zero":compact(first_zero,origin),
        "first_timg12_ack":compact(zero_ack,origin),
        "first_pwm_pair_after_timer_zero":compact(later_pair,origin),
        "last_guest_timg12_start_before_first_zero":compact(latest_start,origin),
        "guest_armed_timg12_remaining_ticks":tick_count,
        "qemu_timg12_expected_virtual_zero_ns":predicted_deadline,
        "timg12_virtual_deadline_error_ns":error_ns,
        "captured_before_first_timg12":caps_out,
        "first_cap1_did_not_observably_arm_timer":not bool(
            caps_out[0]["guest_timer_start_after_read"]),
        "first_then_second_capture_arm_pattern_observed":(
            len(caps_out)>=2 and
            caps_out[0]["guest_timer_start_after_read"] is None and
            caps_out[1]["guest_timer_start_after_read"] is not None),
        "policy_interpretation":"Original Rel17 ival/2 early rejection is "
           "consistent with absent MMIO TIMER START, but the Guest's "
           "internal branch/return value and capture_us are not directly "
           "observable from these hardware events.",
        "status":"PASS_MMIO_SOURCE_CONTRACT" if not faults else
                 "FAIL_MMIO_SOURCE_CONTRACT",
        "issues":faults
    }
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-root",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    results=[]
    for case in CASE_NAMES:
        ep=a.input_root/("e62-p1-script-"+case+".p0.events.log")
        vp=a.input_root/("e62-p1-script-"+case+".p1.json")
        try:
            with ep.open(errors="replace") as inp:
                events=parse_events(inp)
            verdict=json.loads(vp.read_text())
            result=audit(events,verdict,case)
        except (ValueError,OSError,KeyError,TypeError) as e:
            result={"case":case,"status":"FAIL_MMIO_SOURCE_INCOMPLETE",
                    "issues":[str(e)]}
        results.append(result)
        print("E62_FW_PORTING_MMIO "+json.dumps({
            "case":case, "status":result["status"],
            "source_p1":result.get("p1_unchanged_original_verdict"),
            "first_then_second_capture_arm":result.get(
                "first_then_second_capture_arm_pattern_observed"),
            "first_cap1_no_rearm":result.get(
                "first_cap1_did_not_observably_arm_timer"),
            "timg12_error_ns":result.get("timg12_virtual_deadline_error_ns"),
            "captures":[{"cap1_ms":v["cap1"]["ms_after_first_power"],
                         "read_mmio":v["guest_cap1_mmio_read"] is not None,
                         "timer_armed":v["guest_timer_start_after_read"] is not None}
                        for v in result.get("captured_before_first_timg12",[])],
            "issues":result["issues"]},sort_keys=True),flush=True)
    success=all(r["status"]=="PASS_MMIO_SOURCE_CONTRACT" for r in results)
    output={"schema":"e62-fw-porting-mmio-chain.v1","scope":"SIM_ONLY",
            "status":"PASS_MMIO_DIAGNOSTIC_NOT_P1_ACCEPTANCE" if success else
                     "FAIL_MMIO_SOURCE_CONTRACT",
            "qualified_hardware":False,"p0_p1_gates_unchanged":True,
            "cases":results}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(output,sort_keys=True,indent=2)+"\n")
    return 0 if success else 1

if __name__=="__main__":
    raise SystemExit(main())
