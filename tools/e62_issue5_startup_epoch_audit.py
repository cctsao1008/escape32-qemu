#!/usr/bin/env python3
"""Read-only audit of DShot-relative time alignment in E62 Issue #5.

The QEMU event virtual timestamp is an absolute virtual-clock timestamp.
Scenario stage timing begins at the first DSHOT frame, which can be later
than vns=0 when the Guest runs before the Host arms its DShot source.

Never writes artifacts, Guest state, Firmware, or QEMU motor configuration.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import median

MS = 1_000_000
COASTS = (20, 100, 300)
ANGLES = (-90, -30, 0, 90)
EVENT = re.compile(
    r"\bvns=(\d+)\s+kind=(DSHOT|ROTOR|SWITCH_FOCUS_LIMIT)"
    r"(?:\s+a=(-?\d+))?"
)


def rpm_median(samples, lo_ns, hi_ns):
    values = [rpm for ns, rpm in samples if lo_ns <= ns < hi_ns]
    return round(median(values), 3) if values else None


def audit_case(root: Path, coast: int, angle: int):
    name = f"coast{coast:03d}-angle{angle:+04d}"
    base = root / "artifacts/issue5/ztc-robustness"
    metadata_path = base / f"{name}.json"
    trace = base / f"{name}.p0.events.log"
    if not (metadata_path.is_file() and trace.is_file()):
        return {"case": name, "status": "MISSING_ARTIFACT"}
    metadata = json.loads(metadata_path.read_text())
    focus_text = metadata.get("source_focus_window_ms")
    if not isinstance(focus_text, str) or not re.fullmatch(r"\d+:\d+", focus_text):
        return {"case": name, "status": "MISSING_FOCUS_CONTRACT"}
    focus_start, focus_end = (int(v) * MS for v in focus_text.split(":"))
    targets = {0, 1500, 3000, 3000 + coast, 4500 + coast}
    frames = {}
    duplicate = []
    rotors = []
    limits = []
    focus_events = 0
    first_event_ns = None
    with trace.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            match = EVENT.search(line)
            if match:
                ns = int(match.group(1))
                kind = match.group(2)
                field = match.group(3)
                if first_event_ns is None:
                    first_event_ns = ns
                if kind == "DSHOT" and field is not None:
                    index = int(field)
                    if index in targets:
                        if index in frames:
                            duplicate.append(index)
                        else:
                            frames[index] = ns
                elif kind == "ROTOR" and field is not None:
                    rotors.append((ns, int(field) / 1000.0))
                elif kind == "SWITCH_FOCUS_LIMIT":
                    limits.append(ns)
            if "kind=SWITCH_FOCUS " in line:
                focus_events += 1
    missing = sorted(targets - frames.keys())
    if missing or duplicate:
        return {"case": name, "status": "INVALID_DSHOT_FRAME_ANCHORS",
                "missing_frames": missing, "duplicate_frames": duplicate}
    zero = frames[0]
    coast_start = frames[3000]
    coast_end = frames[3000 + coast]
    restart_end = frames[4500 + coast]
    expected_coast_start = zero + 3000 * MS
    expected_coast_end = zero + (3000 + coast) * MS
    drift_start_ns = coast_start - expected_coast_start
    drift_end_ns = coast_end - expected_coast_end
    # Old V2 assumed the first frame happened at QEMU vns=0.
    old_d1 = rpm_median(rotors, 2800 * MS, 3000 * MS)
    actual_d1 = rpm_median(rotors, coast_start - 200 * MS, coast_start)
    d2 = rpm_median(rotors, restart_end - 300 * MS, restart_end)
    return {
        "case": name,
        "status": "OK",
        "dshot_t0_ms": round(zero / MS, 6),
        "actual_coast_start_ms": round(coast_start / MS, 6),
        "coast_start_drift_ns": drift_start_ns,
        "coast_end_drift_ns": drift_end_ns,
        "old_absolute_demand1_rpm": old_d1,
        "dshot_aligned_demand1_rpm": actual_d1,
        "dshot_aligned_demand2_rpm": d2,
        "focus_covers_actual_first20ms": (
            focus_start <= coast_start and
            coast_start + 20 * MS <= focus_end
        ),
        "focus_limit_events": len(limits),
        "focus_events": focus_events,
        "original_probe_status": metadata.get("status"),
        "first_selected_event_ms": (
            round(first_event_ns / MS, 6)
            if first_event_ns is not None else None
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    cases = [
        audit_case(args.root.resolve(), coast, angle)
        for coast in COASTS for angle in ANGLES
    ]
    if args.json:
        print(json.dumps({"schema": "e62.issue5.startup-epoch-audit.v1",
                          "cases": cases}, indent=2))
    else:
        print(
            f'{"CASE":26} {"DShot t0 ms":>12} {"Coast vms":>12} '
            f'{"D1 old":>9} {"D1 aligned":>11} {"D2 aligned":>11} '
            f'{"Focus":>7} {"Drift ns":>10} {"Status":>10}'
        )
        for row in cases:
            print(
                f'{row["case"]:26} '
                f'{str(row.get("dshot_t0_ms","N/A")):>12} '
                f'{str(row.get("actual_coast_start_ms","N/A")):>12} '
                f'{str(row.get("old_absolute_demand1_rpm","N/A")):>9} '
                f'{str(row.get("dshot_aligned_demand1_rpm","N/A")):>11} '
                f'{str(row.get("dshot_aligned_demand2_rpm","N/A")):>11} '
                f'{("YES" if row.get("focus_covers_actual_first20ms") else "NO"):>7} '
                f'{str(row.get("coast_start_drift_ns","N/A")):>10} '
                f'{row["status"]:>10}'
            )
    return 0 if all(row["status"] == "OK" for row in cases) else 2


if __name__ == "__main__":
    raise SystemExit(main())

