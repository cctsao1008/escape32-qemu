#!/usr/bin/env python3
"""E62 read-only first-physical-drive -> CAP1 -> TIMG12 chronology.

Unlike the 1st-positive-DShot-only snapshot, this retains the long 10%
inactive steps epoch and anchors a second view to the actual first powered
PWM_PAIR. No guest writes, synthetic feedback, new clocks or acceptance waiver.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.native_p0_strict import parse_events
from tools.native_p1_causality_ledger import decoded_pair

CASES = ("smoke", "gentle", "direct20", "steps")
KINDS = ("PWM_PAIR", "SWITCH", "CMP_FILTER", "CAP1", "CAP1_ACK",
         "TIMG12", "TIMG12_ACK", "BEMF_FRONTEND", "ROTOR")
ELF_SHA256 = "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
WINDOW_NS = 40_000_000

def ms(value):
    return round(value/1_000_000, 6) if value is not None else None

def first(events, kind, start=0):
    return next((e for e in events if e["kind"] == kind
                 and e["vns"] >= start), None)

def one(e, epoch):
    if e is None:
        return None
    return {"relative_ms": ms(e["vns"]-epoch), "seq": e["seq"],
            "data": list(e["data"])}

def nearest_rotor(events, when):
    if when is None:
        return None
    before = None
    after = None
    for e in events:
        if e["kind"] != "ROTOR":
            continue
        if e["vns"] <= when:
            before=e
        elif after is None:
            after=e
            break
    def compact(e):
        if e is None:
            return None
        d=e["data"]
        return {"virtual_ns":e["vns"], "rpm":d[0]/1000,
                "theta_unwrapped_electrical_deg":math.degrees(d[1]/1000),
                "phase_currents_a":[x/1000 for x in d[2:5]],
                "torque_nm":d[5]/1e6}
    return {"preceding":compact(before), "following":compact(after)}

def audit(events, verdict, case):
    if case not in CASES:
        raise ValueError("Unrecognized strict P1 scenario")
    if verdict.get("status") not in ("PASS_P1_SIM_ONLY_OBSERVABILITY",
                                    "FAIL_P1_SIM_ONLY_OBSERVABILITY"):
        raise ValueError("Missing strict original P1 source verdict")
    if not isinstance(verdict.get("qualified"), bool):
        raise ValueError("Missing P1 qualification boolean")
    src=first(events,"DSHOT")
    onset=next((e for e in events if e["kind"]=="DSHOT" and
                e["data"][2]>0), None)
    if src is None or onset is None:
        raise ValueError("No original positive PA26 DShot")
    pair=first(events,"PWM_PAIR",onset["vns"])
    if pair is None:
        raise ValueError("No physical original Guest PWM_PAIR")
    physical=decoded_pair(pair)
    if not physical["source_pair_id_consistent"]:
        raise ValueError("Invalid original six-pad source pair")
    t0=pair["vns"]
    cap=first(events,"CAP1",t0)
    ack=first(events,"CAP1_ACK",cap["vns"]) if cap else None
    t12=first(events,"TIMG12",cap["vns"]) if cap else None
    t12ack=first(events,"TIMG12_ACK",t12["vns"]) if t12 else None
    nextpair=next((e for e in events if e["kind"]=="PWM_PAIR" and
                   e["vns"]>t0),None)
    # Distinguish 'following' from 'paired'. A CAP1 may be acknowledged
    # more than once or an IRQ may schedule a different TIMG12 event.
    before_t12=[e for e in events if e["kind"]=="CAP1" and t0<=
                e["vns"] < (t12["vns"] if t12 else t0+WINDOW_NS)]
    last_cap_before_t12=before_t12[-1] if before_t12 else None
    filter_pre_cap=next((e for e in reversed(events) if cap and
            e["kind"]=="CMP_FILTER" and e["vns"]<=cap["vns"]),None)
    prior_caps=[one(e,t0) for e in before_t12[:8]]
    prior_acks=[one(e,t0) for e in events if e["kind"]=="CAP1_ACK"
                and cap and cap["vns"]<=e["vns"]<
                  (t12["vns"] if t12 else t0+WINDOW_NS)][:8]
    prior_cmp=[one(e,t0) for e in events if e["kind"]=="CMP_FILTER"
               and t0<=e["vns"]<
                 (t12["vns"] if t12 else t0+WINDOW_NS)][:12]
    source_rotor=[e for e in events if e["kind"]=="ROTOR" and
                  t0<=e["vns"]<t0+WINDOW_NS]
    neg=next((e for e in source_rotor if e["data"][5]<-100000),None)
    rev=next((e for e in source_rotor if e["data"][0]<=-50000),None)
    theta_zero=90.0 # For Phase2-high/Phase1-low, forward torque basis
    # = sqrt(3)*cos(theta_e); only applicable to this physical pair.
    current_pair=(physical["hi_phase"],physical["lo_phase"])
    if current_pair != (2,1):
        theta_zero=None
    # Sampled unwrapped electrical angle crossing the positive-current
    # source-pair sign limit; not a fictitious BEMF event or imposed sector.
    # Once Guest has changed the physical power pair, 90 degrees is
    # no longer the zero-torque angle for the *first* pair. Reject
    # post-commutation crossings instead of crediting them to startup.
    first_pair_end=min((e["vns"] for e in (nextpair,t12)
                        if e is not None),default=t0+WINDOW_NS)
    first_crossing=next((e for e in source_rotor if
             e["vns"]<first_pair_end and theta_zero is not None
             and 90<=math.degrees(e["data"][1]/1000)<180),None)
    stage=next((e for e in reversed(events) if e["kind"]=="DSHOT"
                and e["vns"]<=t0),None)
    selected=[e for e in events if e["kind"] in KINDS and
              t0<=e["vns"]<t0+WINDOW_NS]
    rows=[]
    for e in selected:
        if e["kind"]=="ROTOR":
            # At most 20ms, enough to capture the earliest sign crossover.
            if e["vns"]-t0>20_000_000:
                continue
            d=e["data"]
            rows.append({"kind":"ROTOR","at_ms":ms(e["vns"]-t0),
                        "rpm":d[0]/1000,"theta_elec_deg_unwrapped":
                        round(math.degrees(d[1]/1000),3),
                        "ia_ib_ic_a":[v/1000 for v in d[2:5]],
                        "torque_nm":d[5]/1e6})
        elif e["kind"] in ("BEMF_FRONTEND","SWITCH"):
            # BEMF_FRONTEND is periodic; first 24ms is sufficient.
            if e["vns"]-t0<=24_000_000:
                rows.append({"kind":e["kind"], "at_ms":ms(e["vns"]-t0),
                             "source_data":list(e["data"])})
        else:
            rows.append({"kind":e["kind"], "at_ms":ms(e["vns"]-t0),
                         "source_data":list(e["data"])})
    by_kind={k:sum(e["kind"]==k for e in selected) for k in KINDS}
    cmp_to_cap=(ms(cap["vns"]-filter_pre_cap["vns"])
                if cap and filter_pre_cap else None)
    return {
        "case":case,"p1_source_status":verdict["status"],
        "p1_source_qualified":verdict["qualified"],
        "p1_reversal_count":verdict.get("significant_rotor_direction_changes"),
        "diagnostic_only":True,"threshold_modified":False,
        "original_first_positive_dshot":one(onset,onset["vns"]),
        "first_powered_pwm_after_positive_dshot":one(pair,onset["vns"]),
        "first_powered_pwm_pair":physical,
        "preceding_source_command_at_first_power":one(stage,t0),
        "first_cap1":one(cap,t0),"first_cap1_ack":one(ack,t0),
        "first_timg12_after_cap1":one(t12,t0),
        "first_timg12_ack":one(t12ack,t0),
        "first_next_physical_pwm_pair":one(nextpair,t0),
        "first_prior_cmp_filter_to_cap1_ms":cmp_to_cap,
        "first_capture_to_first_following_timg12_ms":(
             ms(t12["vns"]-cap["vns"]) if cap and t12 else None),
        "first_cap1_ack_to_first_following_timg12_ms":(
             ms(t12["vns"]-ack["vns"]) if ack and t12 else None),
        "first_capture_to_first_following_new_pwm_pair_ms":(
             ms(nextpair["vns"]-cap["vns"]) if cap and nextpair else None),
        "cap1_events_before_first_following_timg12":len(before_t12),
        "last_cap1_before_first_timg12":one(last_cap_before_t12,t0),
        "last_cap1_to_first_timg12_ms":(
            ms(t12["vns"]-last_cap_before_t12["vns"])
            if t12 and last_cap_before_t12 else None),
        "first_powered_to_first_cap1_us":(
            round((cap["vns"]-t0)/1000,3) if cap else None),
        "pinned_rel17_initial_ival_us":10000,
        "pinned_rel17_half_interval_ignore_before_us":5000,
        "first_cap1_early_rejection_policy_consistent_not_proven":bool(
            cap and len(before_t12)>1 and cap["vns"]-t0<5_000_000),
        "original_ival_and_capture_epoch_not_directly_recorded":True,
        "first_sample_at_90deg_electrical_before_first_commutation":one(
            first_crossing,t0),
        "first_pair_geometry_valid_until_ms":ms(first_pair_end-t0),
        "cap1_source_events_before_first_timg12":prior_caps,
        "cap1_ack_source_events_before_first_timg12":prior_acks,
        "cmp_filter_source_events_before_first_timg12":prior_cmp,
        "cap1_to_timg12_pairing_not_proven":True,
        "first_negative_torque_below_minus0p1nm":one(neg,t0),
        "first_reverse_below_minus50rpm":one(rev,t0),
        "negative_torque_before_first_timg12":bool(
             neg and t12 and neg["vns"]<t12["vns"]),
        "reverse_before_first_timg12":bool(
             rev and t12 and rev["vns"]<t12["vns"]),
        "first_powered_pair_positive_torque_zero_theta_deg":theta_zero,
        "first_powered_pair_rotor_state":nearest_rotor(events,t0),
        "first_cap1_rotor_state":nearest_rotor(events,
                                              cap["vns"] if cap else None),
        "first_timg12_rotor_state":nearest_rotor(events,
                                              t12["vns"] if t12 else None),
        "first_negative_torque_rotor_state":nearest_rotor(events,
                                              neg["vns"] if neg else None),
        "source_event_counts_40ms_after_power":by_kind,
        "source_event_timeline_40ms_after_power":rows,
        "interpretation_limit":"Following is not causally paired: Guest may "
           "service several CAP1 events, rearm TIMG12, or filter unrelated "
           "edges. This trace never assumes a one-to-one pairing. The "
           "first_pwm_pair_theta zero is ideal positive source-to-sink "
           "current geometry, not measured net current torque.",
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-root",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    cases=[]
    failures=[]
    for name in CASES:
        trace=args.input_root/f"e62-p1-script-{name}.p0.events.log"
        ver=args.input_root/f"e62-p1-script-{name}.p1.json"
        try:
            with trace.open(errors="replace") as f:
                events=parse_events(f)
            result=audit(events,json.loads(ver.read_text()),name)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            failures.append(f"{name}: {exc}")
            result={"case":name,"error":str(exc),"diagnostic_only":True}
        cases.append(result)
        print("E62_P1_FIRST_FEEDBACK "+json.dumps({
            "case":name, "p1":result.get("p1_source_status"),
            "source_reversal_count":result.get("p1_reversal_count"),
            "start_to_first_power_ms":(result.get(
                 "first_powered_pwm_after_positive_dshot") or {}).get(
                 "relative_ms"),
            "cap1_ms":(result.get("first_cap1") or {}).get("relative_ms"),
            "cap1_ack_ms":(result.get("first_cap1_ack") or {}).get("relative_ms"),
            "timg12_ms":(result.get("first_timg12_after_cap1") or {}).get(
                "relative_ms"),
            "cap1_to_timg12_ms":result.get(
                "first_capture_to_first_following_timg12_ms"),
            "last_cap1_to_timg12_ms":result.get(
                "last_cap1_to_first_timg12_ms"),
            "first_cross90_ms":(result.get(
                "first_sample_at_90deg_electrical_before_first_commutation") or {}).get(
                "relative_ms"),
            "original_startup_half_interval_consistent":result.get(
                "first_cap1_early_rejection_policy_consistent_not_proven"),
            "capture_count_before_timg12":result.get(
                "cap1_events_before_first_following_timg12"),
            "prior_cap1_sources":result.get(
                "cap1_source_events_before_first_timg12"),
            "prior_cap1_ack_sources":result.get(
                "cap1_ack_source_events_before_first_timg12"),
            "prior_cmp_filter_sources":result.get(
                "cmp_filter_source_events_before_first_timg12"),
            "first_next_pwm_pair_ms":(result.get(
                "first_next_physical_pwm_pair") or {}).get("relative_ms"),
            "negative_torque_ms":(result.get(
                "first_negative_torque_below_minus0p1nm") or {}).get(
                "relative_ms"),
            "reverse50_ms":(result.get(
                "first_reverse_below_minus50rpm") or {}).get("relative_ms"),
            "first_cap1_rotor":result.get("first_cap1_rotor_state"),
            "first_timg12_rotor":result.get("first_timg12_rotor_state"),
        },sort_keys=True),flush=True)
    output={"status":"PASS_SOURCE_DIAGNOSTIC_ONLY" if not failures else
            "FAIL_SOURCE_DIAGNOSTIC_INCOMPLETE",
            "qualified":False,"acceptance_policy_changed":False,
            "input_case_count":len(cases),"failures":failures,"cases":cases}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,sort_keys=True,indent=2)+"\n")
    return 1 if failures else 0

if __name__=="__main__":
    raise SystemExit(main())
