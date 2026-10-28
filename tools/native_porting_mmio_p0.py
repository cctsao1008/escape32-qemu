#!/usr/bin/env python3
"""Independent archived P0 original-Guest MMIO-to-virtual-timer replay.

Source trace only. Never derives BEMF/capture from rotor speed or synthesizes
an interrupt. PASS is SIM_ONLY porting-device-timing evidence, not P1.
"""
from __future__ import annotations
import argparse
import json
from collections import Counter
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p0_strict import parse_events
from tools.native_porting_mmio_chain import PINNED_ELF,timer_deadline_from_actual_start

KINDS=("CAP1","CAP1_ACK","ECAP1_CAP1_READ","T12_LOAD","T12_START",
       "TIMG12","TIMG12_ACK","PWM_PAIR")

def audit(events,evidence):
    if evidence.get("original_elf_sha256")!=PINNED_ELF:
        raise ValueError("pinned Original Guest ELF SHA does not match")
    for k in ("used_guest_wfi_or_gdb","host_guest_register_writes",
              "synthetic_timed_bemf_enabled"):
        if evidence.get(k) is not False:
            raise ValueError("invalid source provenance: "+k)
    cnt=Counter(x["kind"] for x in events)
    for k in KINDS:
        if not cnt[k]:
            raise ValueError("missing source event "+k)
    issues=[]
    capture=None
    loaded=None
    pending_timer=None
    awaiting_timg12_ack=None
    matches=0
    timermatches=[]
    first_matches=[]
    for ev in events:
        k=ev["kind"]
        seq=ev["seq"]
        if k=="CAP1":
            if capture is not None:
                issues.append(f"UNREAD_EARLIER_CAP1:{seq}")
            capture={"source":ev,"ack":None}
        elif k=="CAP1_ACK":
            if (capture is None or capture["ack"] is not None or
                ev["data"][2]!=capture["source"]["data"][0]):
                issues.append(f"CAP1_ACK_WITHOUT_MATCHING_CAPTURE:{seq}")
            else:
                capture["ack"]=ev
        elif k=="ECAP1_CAP1_READ":
            if (capture is None or capture["ack"] is None or
                ev["data"][0]!=capture["source"]["data"][0]):
                issues.append(f"CAP1_READ_WITHOUT_MATCHING_CAPTURE_AND_ACK:{seq}")
            else:
                matches+=1
                if len(first_matches)<5:
                    first_matches.append({
                        "physical_cap1_seq":capture["source"]["seq"],
                        "guest_ack_seq":capture["ack"]["seq"],
                        "guest_read_seq":seq,"cap1_ticks":ev["data"][0],
                        "capture_to_ack_ns":capture["ack"]["vns"]-
                                            capture["source"]["vns"]})
                capture=None
        elif k=="T12_LOAD":
            loaded=ev
        elif k=="T12_STOP":
            pending_timer=None
        elif k=="T12_START":
            if pending_timer is not None:
                issues.append(f"TIMER_RESTARTED_WITHOUT_STOP_OR_ZERO:{seq}")
            if loaded is None or ev["data"][0]!=loaded["data"][0]:
                issues.append(f"START_WITHOUT_MATCHING_GUEST_TIMER_LOAD:{seq}")
            if ev["data"][1]!=100_000_000:
                issues.append(f"INVALID_TIMER_CLOCK_CONTRACT:{seq}")
            deadline,ticks=timer_deadline_from_actual_start(ev)
            pending_timer={"start":ev,"deadline":deadline,"ticks":ticks}
            loaded=None
        elif k=="TIMG12":
            if pending_timer is None:
                issues.append(f"ZERO_WITHOUT_ORIGINAL_GUEST_TIMER_START:{seq}")
            else:
                delta=ev["vns"]-pending_timer["deadline"]
                timermatches.append({
                    "start_seq":pending_timer["start"]["seq"],
                    "zero_seq":seq,
                    "remaining_ticks":pending_timer["ticks"],
                    "expected_zero_ns":pending_timer["deadline"],
                    "actual_zero_ns":ev["vns"],"delta_ns":delta})
                if abs(delta)>20:
                    issues.append(f"ZERO_DEADLINE_MISMATCH:{seq}:delta_ns={delta}")
                if not (ev["data"][0]&ev["data"][1]&1):
                    issues.append(f"ZERO_NO_ENABLED_IRQ:{seq}")
                pending_timer=None
            if awaiting_timg12_ack is not None:
                issues.append(f"PREVIOUS_ZERO_UNACKNOWLEDGED:{seq}")
            awaiting_timg12_ack=ev
        elif k=="TIMG12_ACK":
            if (awaiting_timg12_ack is None or
                not (ev["data"][0]&ev["data"][1]&1)):
                issues.append(f"UNEXPECTED_OR_INVALID_ZERO_ACK:{seq}")
            else:
                awaiting_timg12_ack=None
    if capture is not None: issues.append("FINAL_CAP1_MISSING_ACK_OR_READ")
    if awaiting_timg12_ack is not None: issues.append("FINAL_ZERO_UNACKNOWLEDGED")
    if pending_timer is not None: issues.append("FINAL_TIMER_ARM_WITHOUT_ZERO")
    if matches!=cnt["CAP1"]: issues.append("CAP1_ACK_READ_COUNT_MISMATCH")
    if len(timermatches)!=cnt["TIMG12"]: issues.append("TIMER_START_ZERO_COUNT_MISMATCH")
    if cnt["TIMG12_ACK"]!=cnt["TIMG12"]: issues.append("TIMER_ZERO_ACK_COUNT_MISMATCH")
    return {
        "status":"PASS_SOURCE_MMIO_P0_SIM_ONLY" if not issues else
                 "FAIL_SOURCE_MMIO_P0_SIM_ONLY",
        "source_clock":"QEMU_CLOCK_VIRTUAL","original_elf_sha256":PINNED_ELF,
        "no_guest_intervention":True,"hardware_qualified":False,
        "p0_p1_acceptance_unchanged":True,
        "p1_stability_not_tested":True,"issues":issues,
        "source_counts":{k:cnt[k] for k in sorted(cnt)},
        "matched_cap1_ack_guest_read":matches,
        "matched_original_guest_timer_start_zero":len(timermatches),
        "max_absolute_timer_deadline_error_ns":
            max((abs(x["delta_ns"]) for x in timermatches),default=None),
        "first_capture_read_chains":first_matches,
        "first_timer_deadlines":timermatches[:8],
        "last_timer_deadlines":timermatches[-8:],
        "guest_internal_accepted_rejected_decision_directly_seen":False,
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events",type=Path,required=True)
    ap.add_argument("--evidence",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args()
    with a.events.open(errors="replace") as f: events=parse_events(f)
    result=audit(events,json.loads(a.evidence.read_text()))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print("E62_P0_FW_MMIO "+json.dumps({
        k:result[k] for k in ("status","matched_cap1_ack_guest_read",
            "matched_original_guest_timer_start_zero",
            "max_absolute_timer_deadline_error_ns","issues")},sort_keys=True))
    return 1 if result["issues"] else 0

if __name__=="__main__":
    raise SystemExit(main())
