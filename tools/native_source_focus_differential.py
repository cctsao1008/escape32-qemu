#!/usr/bin/env python3
"""Fail-closed E62 OFF/OFF reproducibility gate before OFF/ON attribution.

Reads only completed original QEMU source and energy artifacts.
Never adjusts timestamps, virtual clocks, firmware, plant or P0/P1 gates.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_source_energy_audit import parse_source
from tools.native_source_trace import ELF

FOCUS = {"SWITCH_FOCUS", "SWITCH_FOCUS_LIMIT"}
LIMIT_NS = 2_990_000_000
FOCUS_LO, FOCUS_HI = 2_795_000_000, 2_840_000_000

def original(events):
    return [(e["vns"], e["kind"], tuple(e["data"])) for e in events
            if e["vns"] <= LIMIT_NS and e["kind"] not in FOCUS]

def compare(a, b):
    left, right = original(a), original(b)
    first = next(((i, list(x), list(y)) for i, (x, y) in
                  enumerate(zip(left, right)) if x != y), None)
    if first is None and len(left) != len(right):
        i = min(len(left), len(right))
        first = (i, list(left[i]) if i < len(left) else None,
                 list(right[i]) if i < len(right) else None)
    def first_dshot(seq):
        return next((e["vns"] for e in seq if e["kind"] == "DSHOT"), None)
    return {"equal": first is None, "left_events": len(left),
            "right_events": len(right), "first_difference": first,
            "first_dshot_left_ns": first_dshot(a),
            "first_dshot_right_ns": first_dshot(b)}

def validate_meta(meta, focused):
    assert meta["original_elf_sha256"] == ELF, "Original ELF mismatch"
    assert meta["host_guest_register_writes"] is False
    assert meta["used_guest_wfi_or_gdb"] is False
    assert meta["source_focus_guest_or_motor_control"] is False
    assert meta["motor_mode"] == "QEMU_VIRTUAL_CLOCK_NATIVE_ECX87_KV147_SIM_ONLY"
    assert meta["configured_dshot_frames"] == 3000
    assert meta["source_focus_window_ms"] == ("2795:2840" if focused else None)

def evaluate(off1, off2, on, e1, e2, en, phase):
    result = {"schema": "e62.native.focus-differential.v1", "phase": phase,
              "classification": "NOT_EVALUATED",
              "observer_non_intrusiveness": "NOT_ESTABLISHED",
              "motor_p1_stability_qualified": False,
              "hardware_qualified": False,
              "timebase": "QEMU_CLOCK_VIRTUAL",
              "strict_source_timestamp_match": True}
    try:
        for meta, events in (off1, off2):
            validate_meta(meta, False)
            assert not any(x["kind"] in FOCUS for x in events), "OFF emitted focus"
        baseline = compare(off1[1], off2[1])
        energy_same = e1["energy_delta_j"] == e2["energy_delta_j"]
        result["off_off"] = baseline
        result["off_off_energy_equal"] = energy_same
        if not baseline["equal"] or not energy_same:
            result["classification"] = "FAIL_BASELINE_NONREPRODUCIBLE"
            result["reason"] = "OFF/OFF source or energy differs before observer attribution"
            return result
        if phase == "baseline":
            result["classification"] = "PASS_BASELINE_REPEATABILITY"
            result["observer_non_intrusiveness"] = "NOT_YET_EVALUATED"
            return result
        assert phase == "differential" and on is not None and en is not None
        validate_meta(on[0], True)
        focus = [x for x in on[1] if x["kind"] == "SWITCH_FOCUS"]
        assert len(focus) > 10, "No source-backed focused transitions"
        assert not any(x["kind"] == "SWITCH_FOCUS_LIMIT" for x in on[1]), "Focus budget overflow"
        assert all(FOCUS_LO <= x["vns"] <= FOCUS_HI and
                   0 <= x["data"][0] <= 63 and x["data"][1] in (0, 1)
                   for x in focus), "Focus window/shape invalid"
        assert not en["motor_p1_stability_qualified"], "P1 waiver attempted"
        assert en["late_full_switch_events"] == 0, "Original P0 SWITCH altered"
        assert not e1["focused_switching_source_events"], "OFF source focus not empty"
        assert len(en["focused_switching_source_events"]) > 10
        diff = compare(off1[1], on[1])
        energy_match = e1["energy_delta_j"] == en["energy_delta_j"]
        result.update(off_on=diff, off_on_energy_equal=energy_match,
                      focused_switch_records=len(focus))
        if not diff["equal"] or not energy_match:
            result["classification"] = "FAIL_OFF_ON_DIFFERENTIAL"
            result["reason"] = "OFF/OFF stable; OFF/ON original source or energy differs"
            return result
        result["classification"] = "PASS_STRICT_SOURCE_FOCUS_DIFFERENTIAL"
        result["observer_non_intrusiveness"] = "SUPPORTED_FOR_THIS_REPLAY_ONLY"
        return result
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        result["classification"] = "FAIL_INVALID_DIFFERENTIAL_EVIDENCE"
        result["reason"] = str(exc)
        return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=("baseline", "differential"), required=True)
    p.add_argument("--directory", type=Path, default=Path("artifacts"))
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = {"classification": "FAIL_INVALID_DIFFERENTIAL_EVIDENCE",
              "observer_non_intrusiveness": "NOT_ESTABLISHED",
              "motor_p1_stability_qualified": False, "hardware_qualified": False}
    try:
        base = a.directory
        def bundle(label):
            meta = json.loads((base / f"e62-focus-{label}.json").read_text())
            with (base / f"e62-focus-{label}.p0.events.log").open(
                    encoding="utf-8", errors="replace") as stream:
                events = parse_source(stream)
            return meta, events
        def energy(label):
            return json.loads((base / f"e62-focus-{label}.energy.json").read_text())
        result = evaluate(bundle("off"), bundle("off-repeat"),
                          bundle("on") if a.phase == "differential" else None,
                          energy("off"), energy("off-repeat"),
                          energy("on") if a.phase == "differential" else None,
                          a.phase)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        result["reason"] = type(exc).__name__ + ": " + str(exc)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(result["classification"], json.dumps(result, sort_keys=True))
    return 0 if result["classification"].startswith("PASS_") else 1

if __name__ == "__main__":
    raise SystemExit(main())
