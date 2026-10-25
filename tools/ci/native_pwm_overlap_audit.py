#!/usr/bin/env python3
"""Non-waiving forensic audit of true QEMU PWM event-journal overlaps.

An overlap in the QEMU model is a MODEL/firmware integration concern,
not evidence that the external Si/GaN MOSFET pair physically overlapped.
Do not smooth, clip, or remove a violating event from motor physics.
"""
import argparse
import json
from pathlib import Path

PHASES=("U","V","W")
SOURCE="ORIGINAL_GUEST_WFI_INCREMENTAL_QEMU_INTERNAL_PWM_HISTORY"

def audit(doc):
    h=doc.get("pwm_history") or {}
    events=h.get("events") or []
    errors=[]
    if h.get("scope")!=SOURCE:
        errors.append("missing_original_clocked_QEMU_history_scope")
    if not events:
        errors.append("no_actual_QEMU_PWM_events")
    previous=None
    for x in events:
        if (type(x.get("sequence")) is not int or
            type(x.get("virtual_ns")) is not int or
            type(x.get("new_mask")) is not int or
            x["new_mask"] & ~0x3f):
            errors.append("invalid_event_type")
            break
        if previous is not None:
            if (x["sequence"]!=previous["sequence"]+1 or
                x["virtual_ns"] < previous["virtual_ns"]):
                errors.append("event_sequence_or_virtual_time_gap")
                break
        previous=x
    overlaps=[]
    if not errors:
        for i,x in enumerate(events):
            mask=x["new_mask"]
            bad=[phase for phase,idx in zip(PHASES,range(3))
                 if mask & (3 << (idx*2))==(3 << (idx*2))]
            if not bad:
                continue
            future=events[i+1] if i+1<len(events) else None
            duration=(future["virtual_ns"]-x["virtual_ns"]
                      if future is not None else None)
            overlaps.append({
                "sequence":x["sequence"],
                "virtual_ns":x["virtual_ns"],
                "mask_hex":hex(mask),
                "phases":bad,
                "event_kind":x.get("kind"),
                "observed_at_native_wfi":x.get("observed_at_native_wfi"),
                "duration_until_next_QEMU_event_ns":duration,
                "next_mask_hex":hex(future["new_mask"]) if future else None,
            })
    return {
        "status":("INVALID_TRACE_EVIDENCE" if errors else
                  "FAIL_QEMU_MODELED_PWM_COMPLEMENTARY_OVERLAP"
                  if overlaps else
                  "NO_OVERLAP_IN_OBSERVED_QEMU_HISTORY_ONLY"),
        "issues":errors,
        "qemu_event_count":len(events),
        "overlap_event_count":len(overlaps),
        "modeled_overlap_events":overlaps,
        "duration_quantification":(
            "NEXT_QEMU_EVENT_BOUNDARY_ONLY_NOT_OSCILLOSCOPE"),
        "known_qemu_event_clock_not_external_gate":True,
        "silicon_mosfet_shootthrough_qualified":False,
        "strict_rotor_failure_not_waived":True,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--history",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    result=audit(json.loads(args.history.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("E62_G14_QEMU_PWM_OVERLAP_FORENSICS "+
          json.dumps(result,sort_keys=True),flush=True)
    return 0  # Diagnostic only: the independent native gate remains red.

if __name__=="__main__":
    raise SystemExit(main())
