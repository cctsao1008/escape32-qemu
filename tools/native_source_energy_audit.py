#!/usr/bin/env python3
"""Read-only E62 native ENERGY/INVARIANT ledger audit around DShot neutral.

Operates ONLY on complete original QEMU E62_P0_EVENT stderr. No Guest
probe, MMIO, virtual-time stepping, motor model change or P1 gate waiver.
ENERGY fields are signed, cumulative 1e-9 Joule model integrals.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.native_source_trace import ELF, read_source_line, SourceTraceError

NAMES=("bus","diode","copper","bemf","magnetic","backward_euler")
MAX_LOG_BYTES=64*1024*1024
WINDOW_NS=35_000_000
MAX_EVENTS=150000
SERIALIZATION_NJ=6

class EnergyAuditError(ValueError):
    pass

def parse_source(lines):
    """Original source order and event identity must be complete, no filling."""
    parsed=[]
    previous_seq=0
    previous_ns=-1
    for line in lines:
        try:
            e=read_source_line(line)
        except SourceTraceError as exc:
            raise EnergyAuditError(str(exc)) from exc
        if e is None:
            continue
        if e["seq"]!=previous_seq+1 or e["vns"]<previous_ns:
            raise EnergyAuditError("Nonconsecutive source sequence or virtual time reversal")
        previous_seq=e["seq"]
        previous_ns=e["vns"]
        parsed.append(e)
        if len(parsed)>MAX_EVENTS:
            raise EnergyAuditError("Source event budget exceeded")
    if not parsed:
        raise EnergyAuditError("Missing actual E62_P0_EVENT source records")
    return parsed

def audit(events, *, window_ns=WINDOW_NS):
    if not 1_000_000<=window_ns<=500_000_000:
        raise EnergyAuditError("Energy focus window must be 1..500 ms")
    seq_prev=0
    t_prev=-1
    for e in events:
        if (e["seq"]!=seq_prev+1 or e["vns"]<t_prev or
            len(e["data"])!=6):
            raise EnergyAuditError("Source order/gap/shape invalid")
        seq_prev=e["seq"]
        t_prev=e["vns"]
    trigger=None
    preceding=None
    last_raw=None
    for e in events:
        if e["kind"]=="DSHOT":
            raw=e["data"][2]
            if last_raw is not None and last_raw>0 and raw==0:
                trigger=e
                preceding=last_raw
            last_raw=raw
    if trigger is None:
        raise EnergyAuditError("No observed DShot nonzero to 0 source event")
    t0=trigger["vns"]
    t1=t0+window_ns
    energy=[e for e in events if e["kind"]=="ENERGY"]
    invariant=[e for e in events if e["kind"]=="INVARIANT"]
    if not energy or not invariant:
        raise EnergyAuditError("Missing model ENERGY/INVARIANT sources")
    if energy[0]["vns"]>t0 or energy[-1]["vns"]<t1:
        raise EnergyAuditError("Source does not cover full target energy window")
    post=[e for e in energy if t0<=e["vns"]<=t1]
    prev=[e for e in energy if e["vns"]<t0]
    if len(post)<2 or not prev:
        raise EnergyAuditError("Insufficient source energy points across neutral")
    first,last=post[0],post[-1]
    baseline=prev[-1]
    ledger_residuals=[
        e["data"][0]-sum(e["data"][1:]) for e in energy
    ]
    max_residual=max(abs(x) for x in ledger_residuals)
    if max_residual>SERIALIZATION_NJ:
        raise EnergyAuditError("Original model cumulative electrical ledger inconsistent")
    if any(e["data"][i]<0 for e in energy for i in (1,2,5)):
        raise EnergyAuditError("Negative cumulative dissipation/numerical loss")
    if any(x["data"][3]>10000 or x["data"][4]>10 for x in invariant):
        raise EnergyAuditError("Original QEMU invariant exceeded source threshold")
    def increments(a,b):
        return {name:(b["data"][i]-a["data"][i])/1e9 for i,name in enumerate(NAMES)}
    delta=increments(first,last)
    pre_delta=increments(baseline,first)
    ledger_difference=delta["bus"]-sum(v for k,v in delta.items() if k!="bus")
    if abs(ledger_difference)>12e-9:
        raise EnergyAuditError("Neutral-window energy ledger fails closed")
    source_window=[e for e in events if t0<=e["vns"]<=t1]
    count=Counter(e["kind"] for e in source_window)
    pwm=[e for e in source_window if e["kind"]=="PWM_PAIR"]
    enabled_pwm=[
        e for e in pwm if (e["data"][2]&0xF)==0xF
    ]
    switches=[e for e in source_window if e["kind"]=="SWITCH"]
    focus=[e for e in source_window if e["kind"]=="SWITCH_FOCUS"]
    focus_limited=[e for e in events if e["kind"]=="SWITCH_FOCUS_LIMIT"]
    if focus_limited:
        raise EnergyAuditError("Focused source SWITCH event budget exceeded")
    negative_bus_segments=sum(
        b["data"][0]<a["data"][0] for a,b in zip(post,post[1:])
    )
    result={
        "schema":"e62.native.neutral-energy-audit.v1",
        "classification":"SOURCE_MODEL_LEDGER_VALID_CAUSAL_MECHANISM_OPEN",
        "source":"ORIGINAL_QEMU_E62_P0_EVENT_READ_ONLY",
        "timebase":"QEMU_CLOCK_VIRTUAL",
        "elf_sha256":ELF,
        "source_event_count":len(events),
        "source_last_seq":events[-1]["seq"],
        "motor_p1_stability_qualified":False,
        "hardware_qualified":False,
        "trigger":{
            "seq":trigger["seq"],"t_ns":t0,
            "previous_dshot_raw":preceding,"neutral_dshot_raw":0
        },
        "window":{"requested_from_ns":t0,"requested_to_ns":t1,
                  "duration_ms":window_ns/1e6,
                  "first_energy_ns":first["vns"],
                  "last_energy_ns":last["vns"],
                  "energy_samples":len(post),
                  "full_source_coverage":True,
                  "no_interpolation":True},
        "energy_units":"J (signed change in cumulative 1e-9 J source model counters)",
        "energy_delta_j":delta,
        "pre_to_first_energy_delta_j":pre_delta,
        "pre_baseline_ns":baseline["vns"],
        "energy_identity_residual_j":ledger_difference,
        "whole_source_max_serialization_residual_nj":max_residual,
        "negative_dc_bus_energy_intervals":negative_bus_segments,
        "energy_intervals":len(post)-1,
        "invariant_last_source":invariant[-1]["data"],
        "source_events_in_window":{
            key:count[key] for key in
            ("DSHOT","PWM_PAIR","SWITCH","SWITCH_FOCUS",
             "CAP1","TIMG12","ENERGY","INVARIANT")
        },
        "powered_pwm_pairs_after_neutral":[
            {"seq":e["seq"],"t_ns":e["vns"],
             "pair":e["data"][0],"mask":e["data"][1],
             "gate_word":e["data"][2]}
            for e in enabled_pwm
        ],
        "late_full_switch_events":len(switches),
        "focused_switching_source_events":[
            {"seq":e["seq"],"t_ns":e["vns"],
             "six_pad_mask":e["data"][0],"gate_valid":bool(e["data"][1]),
             "gate_word":e["data"][2],
             "native_motor_integrated_steps":e["data"][3],
             "pwm_zero_callbacks":e["data"][4],
             "pwm_event_counter_before":e["data"][5]}
            for e in focus
        ],
        "focused_switch_source_records_present_without_budget_overrun":bool(focus) and not focus_limited,
        "inference_limits":[
            "NEGATIVE_BEMF_ENERGY_IS_SOURCE_MODEL_MECHANICAL_TO_ELECTRICAL_TRANSFER",
            "NEGATIVE_DC_BUS_ENERGY_CHANGE_IS_MODEL_INTEGRAL_NOT_PHYSICAL_BATTERY_CHARGE",
            "PWM_PAIR_PROVES_OBSERVED_POWER_PAIR_CHANGE_NOT_COMPLETE_CARRIER",
            "NO_ACTIVE_BRAKE_OR_COAST_CAUSAL_CLASSIFICATION",
            "UNWAIVED_MOTOR_P1_STABILITY_GATE",
        ],
    }
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    p.add_argument("--window-ms",type=int,default=35)
    p.add_argument("--expected-sha256",default=None)
    args=p.parse_args()
    if args.events.resolve()==args.output.resolve():
        p.error("Refusing overwrite of original source log")
    if args.events.stat().st_size>MAX_LOG_BYTES:
        p.error("Original source log exceeds 64MiB safety budget")
    if args.expected_sha256:
        digest=hashlib.sha256(args.events.read_bytes()).hexdigest()
        if digest!=args.expected_sha256:
            p.error("Original source log SHA256 differs from expected evidence")
    try:
        with args.events.open(errors="replace",encoding="utf-8") as inp:
            result=audit(parse_source(inp),window_ns=args.window_ms*1_000_000)
    except (ValueError,OSError,TypeError,KeyError) as exc:
        p.error(str(exc))
    result["source_log_sha256"]=hashlib.sha256(args.events.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("E62_NEUTRAL_ENERGY_AUDIT "+json.dumps({
        "classification":result["classification"],
        "source_log_sha256":result["source_log_sha256"],
        "trigger":result["trigger"],
        "energy_delta_j":result["energy_delta_j"],
        "source_events_in_window":result["source_events_in_window"],
        "focused_switch_event_count":len(
            result["focused_switching_source_events"]),
        "motor_p1_stability_qualified":False,
        "output":str(args.output),
    },sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
