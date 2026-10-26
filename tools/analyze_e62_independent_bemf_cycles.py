#!/usr/bin/env python3
"""Offline phase-cycle-slip audit of real E62 original-Guest SITL JSON.

No QEMU rerun, Guest writes, fictitious captures, phase feedback or
assumption that source WFI time = exact comparator zero-crossing.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median


def analyze(evidence):
    assert evidence.get("bemf_input_mode") == "INDEPENDENT_THREE_PHASE_FIXED_HZ"
    hz = evidence["independent_bemf_diagnostics"]["electrical_hz"]
    assert 1 <= hz <= 2000
    stages = evidence["stages"]
    hold = next(x for x in stages if x["kind"] == "hold")
    a, b = hold["start_ns"], hold["end_ns"]
    sectors = evidence["six_phase_audit"]["sectors"]
    hold_sectors = [
        x for x in sectors
        if a <= x["commutation_wfi_bracket_ns"][1] < b
    ]
    intervals = []
    hist = Counter()
    for old, new in zip(hold_sectors, hold_sectors[1:]):
        if (new["serviced_after"] != old["serviced_after"] + 1 or
            new["new_guest_step"] != old["new_guest_step"] % 6 + 1):
            continue
        dt = new["commutation_wfi_bracket_ns"][1] - old["commutation_wfi_bracket_ns"][1]
        if dt <= 0:
            raise ValueError("Non-increasing Guest commutation timestamp")
        phase_cycles = dt * hz / 1e9
        intervals.append(phase_cycles)
        extra = round(phase_cycles - 1/6)
        if extra >= 0 and abs(phase_cycles - (extra + 1/6)) <= 0.20:
            hist[str(extra)] += 1
        else:
            hist["not_near_60deg_plus_whole_cycles"] += 1
    cycles = evidence["independent_bemf_diagnostics"]["phase_center_sign_changes"]
    caps = evidence["independent_bemf_diagnostics"]["source_cap1_count_from_guest"]
    services = hold["original_timg12_service_delta"]
    exp = 6 * hz * (b-a)/1e9
    observed = services/((b-a)/1e9)
    return {
        "input_electrical_hz": hz,
        "full_original_guest_functional_status": evidence["status"],
        "input_three_phase_sign_changes_full_11s": cycles,
        "original_guest_cap1_count_full_11s": caps,
        "cap1_per_input_three_phase_sign_change": caps/cycles,
        "guest_hold_services": services,
        "ideal_hold_six_step_services": exp,
        "hold_commutation_to_expected_ratio": services/exp,
        "hold_sectors_with_guest_wfi_time": len(hold_sectors),
        "consecutive_sector_interval_count": len(intervals),
        "median_electrical_cycles_per_guest_step": median(intervals) if intervals else None,
        "median_degrees_per_guest_step": 360*median(intervals) if intervals else None,
        "extra_full_electrical_cycles_before_next_guest_step_histogram": dict(hist),
        "expected_normal_electrical_cycles_per_step": 1/6,
        "expected_normal_degrees_per_step": 60,
        "scope": "ORIGINAL_GUEST_WFI_BRACKETED_SECTOR_TIMING_NOT_EXACT_CAP1_CROSSING",
        "physical_rotor_electrical_phase_lock_qualified": False,
    }


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("evidence", nargs="+", type=Path)
    ap.add_argument("--output", type=Path)
    args=ap.parse_args()
    rows=[analyze(json.loads(p.read_text(encoding="utf-8"))) for p in args.evidence]
    result={"scope":"OFFLINE_E62_INDEPENDENT_FIXED_BEMF_ORIGINAL_GUEST_RATE_DIAGNOSTIC",
            "points":rows}
    text=json.dumps(result, indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text,encoding="utf-8")
    print(text,end="")


if __name__=="__main__":
    main()
