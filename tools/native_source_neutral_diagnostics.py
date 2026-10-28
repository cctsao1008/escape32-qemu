#!/usr/bin/env python3
"""Report source-observed DShot->neutral dynamics, NEVER classify braking.

Only reads an existing e62.sitl.native-source.v1 JSON. No QEMU/Guest/MMIO
operations, no simulated transitions, no interpolation, no changed P1 gates.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

FORMAT="e62.sitl.native-source.v1"
ELF="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
WINDOW_NS=35_000_000

class ObservationError(ValueError):
    pass

def inspect_neutral_return(doc:dict, *, window_ns=WINDOW_NS)->dict:
    if (not isinstance(doc,dict) or doc.get("format")!=FORMAT or
        doc.get("scope")!="SIM_ONLY_NATIVE_NO_WFI_SOURCE_ONLY" or
        doc.get("metadata",{}).get("elf_sha256")!=ELF or
        doc.get("metadata",{}).get("timebase")!="QEMU_CLOCK_VIRTUAL" or
        not isinstance(doc.get("samples"),list) or
        not isinstance(doc.get("events"),list)):
        raise ObservationError("Requires pinned, QEMU-virtual-time, No-WFI source document")
    if not 1_000_000<=window_ns<=500_000_000:
        raise ObservationError("Focus window 1 to 500 ms only")
    events=doc["events"]
    samples=doc["samples"]
    last_seq=0
    previous_dshot=None
    last_zero=None
    last_previous_raw=None
    for e in events:
        if (not isinstance(e,dict) or not isinstance(e.get("seq"),int) or
            e["seq"]<=last_seq or not isinstance(e.get("t_ns"),int) or
            not isinstance(e.get("data"),list) or len(e["data"])!=6):
            raise ObservationError("Malformed or nonmonotonic source event journal")
        last_seq=e["seq"]
        if e.get("kind")=="DSHOT":
            raw=e["data"][2]
            if not isinstance(raw,int):
                raise ObservationError("Invalid original external FC DShot raw code")
            if previous_dshot is not None and previous_dshot>0 and raw==0:
                last_zero=e
                last_previous_raw=previous_dshot
            previous_dshot=raw
    if last_zero is None:
        raise ObservationError("No source-owned DShot nonzero->0 event observed")
    start=last_zero["t_ns"]
    end=start+window_ns
    timeline=[]
    prev_ns=-1
    for s in samples:
        if not isinstance(s,dict) or not isinstance(s.get("t_ns"),int) or s["t_ns"]<=prev_ns:
            raise ObservationError("Nonmonotonic sample virtual time")
        prev_ns=s["t_ns"]
        if start<=s["t_ns"]<=end:
            timeline.append(s)
    if not timeline:
        raise ObservationError("No ROTOR/BEMF source samples in neutral window")
    relevant=[e for e in events if start<=e["t_ns"]<=end]
    counters=Counter(e["kind"] for e in relevant)
    phases=[i for s in timeline for i in s["phase_currents_a"]]
    bemfs=[s["bemf_codes"] for s in timeline]
    pwm=[s for s in timeline if s["pwm_six_pad_mask"] is not None]
    peak=max(timeline,key=lambda s:max(abs(x) for x in s["phase_currents_a"]))
    most_negative=min(timeline,key=lambda s:s["torque_nm"])
    return {
        "schema":"e62.native.neutral-source-observation.v1",
        "classification":"SOURCE_OBSERVATION_ONLY_MECHANISM_UNDETERMINED",
        "hardware_qualified":False,
        "motor_p1_stability_qualified":False,
        "original_elf_sha256":ELF,
        "timebase":"QEMU_CLOCK_VIRTUAL",
        "source":"E62_P0_EVENT_NO_WFI_READ_ONLY",
        "trigger":{"kind":"DSHOT","seq":last_zero["seq"],
                   "t_ns":start,"previous_raw":last_previous_raw,
                   "new_raw":0},
        "window":{"from_ns":start,"to_ns":end,"duration_ms":window_ns/1e6,
                  "source_samples":len(timeline),
                  "source_events":len(relevant),
                  "fully_covered":samples[0]["t_ns"]<=start and samples[-1]["t_ns"]>=end},
        "rpm":{"first":timeline[0]["motor_rpm"],"last":timeline[-1]["motor_rpm"],
               "minimum":min(s["motor_rpm"] for s in timeline),
               "maximum":max(s["motor_rpm"] for s in timeline)},
        "torque":{"minimum_nm":most_negative["torque_nm"],
                  "minimum_at_ns":most_negative["t_ns"],
                  "maximum_nm":max(s["torque_nm"] for s in timeline)},
        "phase_currents":{"maximum_sampled_absolute_a":max(abs(x) for x in phases),
                          "peak_at_ns":peak["t_ns"]},
        "bemf_code_range":{
            key:{"min":min(a[k] for a in bemfs),
                 "max":max(a[k] for a in bemfs)}
            for k,key in enumerate(("U","V","W"))
        },
        "source_events_in_window":{
            key:counters[key] for key in
            ("DSHOT","PWM_PAIR","CAP1","TIMG12","WWDT_FEED")
        },
        "fresh_pwm_switch_masks_in_window":len(pwm),
        "pwm_carrier_after_startup":"NOT_CAPTURED_BY_BOUNDED_120MS_SWITCH_SOURCE",
        "restrictions":[
            "NO_CAUSAL_INFERENCE_OF_ACTIVE_BRAKE_OR_PASSIVE_COAST",
            "NO_COMPLETE_16KHZ_CARRIER_SWITCH_EDGES_IN_LATE_WINDOW",
            "SIM_ONLY_UNCALIBRATED_MOTOR",
            "NOT_A_STRICT_MOTOR_P1_GATE",
        ],
    }

def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace",type=Path,required=True)
    p.add_argument("--window-ms",type=int,default=35)
    p.add_argument("--output",type=Path)
    args=p.parse_args()
    if args.trace.stat().st_size>50*1024*1024:
        p.error("Trace >50MiB; refusing oversized JSON")
    try:
        result=inspect_neutral_return(json.loads(args.trace.read_text()),
                                      window_ns=args.window_ms*1_000_000)
    except (ValueError,KeyError,TypeError) as exc:
        p.error(str(exc))
    print("E62_NEUTRAL_SOURCE_OBSERVATION "+json.dumps(result,sort_keys=True))
    if args.output:
        if args.output.resolve()==args.trace.resolve():
            p.error("Refusing overwrite of source evidence input")
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
