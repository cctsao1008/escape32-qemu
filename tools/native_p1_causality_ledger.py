#!/usr/bin/env python3
"""Read-only P1 original Guest reversal causality ledger.

Consumes source-ordered QEMU E62_P0_EVENT records and the *unchanged*
P1 verdicts. Never actuates guest memory, PWM, IRQ, BEMF or physics.
This is diagnostic evidence, not a replacement/waiver for P0/P1.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.native_p0_strict import parse_events, TraceError
from tools.e62_native_scripted_test import CASES

SIGNIFICANT_RPM = 50.0  # Existing P1 gate, deliberately unchanged.
CASE_ORDER = ("smoke", "gentle", "direct20", "steps")
DIAGNOSTIC_TORQUE_NM = -0.1  # Marker only; never an acceptance threshold.
DIAGNOSTIC_CURRENT_A = 10.0  # Marker only; never an acceptance threshold.
EVENT_TYPES = ("DSHOT", "PWM_PAIR", "SWITCH", "ROTOR", "BEMF_FRONTEND",
               "CMP_FILTER", "CAP1", "CAP1_ACK", "TIMG12", "TIMG12_ACK")


def compact(event):
    if event is None:
        return None
    return {"seq": event["seq"], "vns": event["vns"],
            "kind": event["kind"], "data": list(event["data"])}


def decoded_pair(event):
    """PWM_PAIR source: a=1+3*HI_phase+LO_phase, b=physical 6-pad mask,
    c=raw AQ/DB gate word, d=rotor electrical unwrapped mrad,
    e=guest PWM zero-event count. No inferred PWM duty is substituted.
    """
    if event is None:
        return None
    d = event["data"]
    mask = d[1] & 63
    hi = [p for p in range(3) if mask & (1 << (2*p))]
    lo = [p for p in range(3) if mask & (1 << (2*p+1))]
    valid = len(hi) == len(lo) == 1 and hi[0] != lo[0]
    return {"vns": event["vns"], "seq": event["seq"], "pair_id": d[0],
            "six_pad_mask": mask, "raw_aq_db_gate_word": d[2],
            "unwrapped_electrical_angle_rad": d[3]/1000,
            "pwm_zero_event_count": d[4],
            "hi_phase": hi[0] if len(hi) == 1 else None,
            "lo_phase": lo[0] if len(lo) == 1 else None,
            "valid_one_high_one_low": valid,
            "source_pair_id_consistent": valid and
               d[0] == 1 + 3*hi[0] + lo[0]}


def rotor_sample(e):
    d=e["data"]
    return {"vns":e["vns"],"rpm":d[0]/1000,
            "unwrapped_electrical_angle_rad":d[1]/1000,
            "phase_current_a":[x/1000 for x in d[2:5]],
            "torque_nm":d[5]/1e6}


def first(items, condition=lambda e: True):
    return next((e for e in items if condition(e)), None)


def event_neighbors(events, at_ns, *, n=4):
    """Per-kind nearest source events around the physical witness timestamp.
    Respect same-ns source sequence instead of assuming a causal link.
    """
    if at_ns is None:
        return None
    out={}
    for kind in EVENT_TYPES:
        sub=[e for e in events if e["kind"]==kind]
        before=[e for e in sub if e["vns"]<=at_ns]
        after=[e for e in sub if e["vns"]>at_ns]
        out[kind]={
            "preceding":[compact(e) for e in before[-n:]],
            "following":[compact(e) for e in after[:n]],
            "prior_count":len(before),
        }
    return out


def diagnose(name, events, verdict=None):
    """Describe *observations*, do not declare a physical root cause."""
    verdict=verdict or {}
    rotor=[e for e in events if e["kind"]=="ROTOR"]
    dshot=[e for e in events if e["kind"]=="DSHOT"]
    onset=first(dshot,lambda e:e["data"][2]>0)
    if onset is None or not rotor:
        raise ValueError("No physical positive DShot or 1ms native rotor")
    first20=first(dshot,lambda e:e["data"][2]>=448)
    # Steps has a 500ms 10% hold before its 20% impulse. The primary
    # startup anchor and the high-command comparison anchor differ.
    anchor=first20 or onset
    end_positive=next((e["vns"] for e in reversed(dshot)
                       if e["data"][2]>0),None)
    active=[e for e in rotor if onset["vns"]<=e["vns"]<=end_positive]
    from_anchor=[e for e in rotor if anchor["vns"]<=e["vns"]<=end_positive]
    first_forward=first(active,lambda e:e["data"][0]>=50000)
    first_reverse=first(active,lambda e:e["data"][0]<=-50000)
    first_neg_torque=first(from_anchor,lambda e:e["data"][5]<-100000)
    first_high_current=first(from_anchor,lambda e:
                             max(abs(x) for x in e["data"][2:5])>=10000)
    sign_before=None
    change=None
    changes=0
    for e in active:
        speed=e["data"][0]
        if abs(speed)<50000:
            continue
        sign=1 if speed>0 else -1
        if sign_before is not None and sign!=sign_before:
            changes+=1
            if change is None:
                change=e
        sign_before=sign
    feedback_kinds=("CMP_FILTER","CAP1","CAP1_ACK","TIMG12",
                    "TIMG12_ACK","PWM_PAIR")
    feedback_first={k:first(events,lambda e:e["kind"]==k and
                       e["vns"]>=anchor["vns"]) for k in feedback_kinds}
    pairs=[e for e in events if e["kind"]=="PWM_PAIR" and
           anchor["vns"]<=e["vns"]<=end_positive]
    sixpad_switch=[e for e in events if e["kind"]=="SWITCH"]
    # SWITCH source is explicitly limited to first 120ms after the
    # very first powered edge. Lack of SWITCH later is NOT absence of AQ.
    selected=[e for e in events if e["kind"] in EVENT_TYPES
              and anchor["vns"]<=e["vns"]<=anchor["vns"]+50_000_000]
    critical={
        "first_positive_dshot":onset,
        "first_dshot_at_or_above_20pct":first20,
        "first_forward_50rpm":first_forward,
        "first_reverse_minus50rpm":first_reverse,
        "first_significant_direction_change":change,
        "first_negative_torque_below_minus0p1nm":first_neg_torque,
        "first_phase_current_at_or_above_10a":first_high_current,
        **{"first_after_anchor_"+k.lower():v
           for k,v in feedback_first.items()},
    }
    observations={k:compact(v) for k,v in critical.items()}
    delays_ms={k:(round((v["vns"]-anchor["vns"])/1e6,6)
                  if v is not None else None) for k,v in critical.items()}
    pivot=first_neg_torque or first_reverse or change or first_forward
    witness=event_neighbors(events,pivot["vns"] if pivot else None)
    preview=[e for e in rotor if anchor["vns"]<=e["vns"]<
             anchor["vns"]+50_000_000]
    pivot_rotor=([e for e in rotor if pivot and
                  pivot["vns"]-10_000_000<=e["vns"]<=
                  pivot["vns"]+15_000_000] if pivot else [])
    phase_current_peak=max((abs(x) for e in preview
                           for x in e["data"][2:5]),default=0)/1000
    torque_min=min((e["data"][5] for e in preview),default=0)/1e6
    physical_pair_rows=[decoded_pair(e) for e in pairs[:24]]
    invalid_pairs=[x for x in (decoded_pair(e) for e in pairs)
                   if not x["source_pair_id_consistent"]]
    at_reversal=change or first_reverse
    first_t12=feedback_first["TIMG12"]
    return {
        "case":name,
        "status":"SOURCE_CAUSAL_DIAGNOSTIC_ONLY_NOT_QUALIFICATION",
        "p1_source_status":verdict.get("status","NOT_AVAILABLE"),
        "p1_source_qualified":verdict.get("qualified"),
        "p1_source_failures":verdict.get("unwaived_observability_failures"),
        "p1_source_direction_changes":verdict.get(
            "significant_rotor_direction_changes"),
        "diagnostic_recomputed_direction_changes":changes,
        "first_50rpm_significant_direction_change":observations[
            "first_significant_direction_change"],
        "anchor_kind":"FIRST_GE20PCT" if first20 else "FIRST_POSITIVE",
        "source_timestamps_ns":observations,
        "relative_to_comparison_anchor_ms":delays_ms,
        "first_50ms_after_anchor":{
            "motor_sample_count":len(preview),
            "peak_abs_phase_current_a":phase_current_peak,
            "minimum_torque_nm":torque_min,
            "source_event_counts":dict(Counter(e["kind"] for e in selected)),
            "rotor_samples":[rotor_sample(e) for e in preview[:50]],
        },
        "source_pwm_pair_count_after_anchor":len(pairs),
        "pwm_pair_sector_sequence_start":physical_pair_rows,
        "pwm_pair_invalid_source_masks":len(invalid_pairs),
        "pwm_pair_invalid_examples":invalid_pairs[:5],
        "source_switch_first_120ms_only":{
            "record_count":len(sixpad_switch),
            "first":compact(first(sixpad_switch)),
            "last":compact(sixpad_switch[-1]) if sixpad_switch else None,
            "not_a_complete_later_carrier_edge_record":True,
        },
        "pivot_type":(pivot["kind"] if pivot else None),
        "pivot_source_event":compact(pivot),
        "pivot_1ms_rotor_window":[rotor_sample(e) for e in pivot_rotor],
        "pivot_source_neighbors":witness,
        "first_negative_speed_before_first_post_anchor_timg12":(
            first_reverse["vns"]<first_t12["vns"]
            if first_reverse is not None and first_t12 is not None else None),
        "first_sign_change_before_first_post_anchor_timg12":(
            change["vns"]<first_t12["vns"]
            if change is not None and first_t12 is not None else None),
        "causality_limit":"Source time order establishes temporal precedence, "
            "not whether model, Guest startup or capture feedback is defective. "
            "A PWM_PAIR mask reports six-pad AQ/DB output, not Guest intent. "
            "SWITCH carrier edges are source-recorded for first 120ms only.",
        "acceptance_policy_modified":False,
    }


def run(records, output):
    reports=[]
    issues=[]
    for name,events_path,verdict_path in records:
        if name not in CASES:
            raise ValueError("Unknown pinned scenario: "+name)
        try:
            with events_path.open(errors="replace") as stream:
                events=parse_events(stream)
            verdict=json.loads(verdict_path.read_text())
            if not isinstance(verdict,dict):
                raise ValueError("Verdict not an object")
            report=diagnose(name,events,verdict)
            if (report["p1_source_direction_changes"] is not None and
                report["diagnostic_recomputed_direction_changes"] !=
                    report["p1_source_direction_changes"]):
                issues.append(name+": DIRECTION_CHANGE_COUNTER_DISAGREEMENT")
            if not report["p1_source_status"].startswith(
                    ("PASS_P1_","FAIL_P1_")):
                issues.append(name+": MISSING_OR_WRONG_SOURCE_P1_VERDICT")
        except (OSError,ValueError,KeyError,TypeError,TraceError) as exc:
            issues.append(name+": "+type(exc).__name__+": "+str(exc))
            report={"case":name,"status":"SOURCE_DIAGNOSTIC_MISSING",
                    "error":str(exc),"p1_source_qualified":None}
        reports.append(report)
        print("E62_P1_CAUSAL_CASE "+json.dumps({
            "case":name,"p1_source_qualified":report.get("p1_source_qualified"),
            "diagnostic_issue":issues[-1] if issues and
                    issues[-1].startswith(name+":") else None,
            "significant_changes":report.get(
                "diagnostic_recomputed_direction_changes"),
            "first_negative_torque_ms":(
                report.get("relative_to_comparison_anchor_ms") or {}
                ).get("first_negative_torque_below_minus0p1nm"),
            "first_reverse_50rpm_ms":(
                report.get("relative_to_comparison_anchor_ms") or {}
                ).get("first_reverse_minus50rpm"),
            "first_timg12_ms":(
                report.get("relative_to_comparison_anchor_ms") or {}
                ).get("first_after_anchor_timg12"),
            "first50_peak_phase_current_a":(
                report.get("first_50ms_after_anchor") or {}
                ).get("peak_abs_phase_current_a"),
            "first50_min_torque_nm":(
                report.get("first_50ms_after_anchor") or {}
                ).get("minimum_torque_nm"),
        },sort_keys=True),flush=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({
        "status":"SOURCE_DIAGNOSTIC_COMPLETE" if not issues else
                 "SOURCE_DIAGNOSTIC_INCOMPLETE",
        "diagnostic_only":True,"qualified":False,
        "acceptance_policy_modified":False,
        "issues":issues,"cases":reports,
    },indent=2,sort_keys=True)+"\n")
    return 0 if not issues else 1


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-root",type=Path,
                   default=ROOT/"artifacts/e62-p1-scripted")
    p.add_argument("--output",type=Path,
                   default=ROOT/"artifacts/e62-p1-scripted/e62-p1-causality.json")
    args=p.parse_args()
    records=[(name,
              args.input_root/("e62-p1-script-"+name+".p0.events.log"),
              args.input_root/("e62-p1-script-"+name+".p1.json"))
             for name in CASE_ORDER]
    raise SystemExit(run(records,args.output))


if __name__=="__main__":
    main()
