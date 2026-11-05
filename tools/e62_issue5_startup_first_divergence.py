#!/usr/bin/env python3
"""Read-only comparison of two synchronized E62 startup QEMU event traces.

Time zero is each run's DShot frame 1500 (first 20% throttle frame).
This diagnostic only finds the earliest observed divergence; an event
difference is not automatically the root cause of motor instability.
No Guest, QEMU plant, or artifact modifications.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from statistics import median

MS = 1_000_000
KINDS = ("ROTOR", "PWM_PAIR", "CAP1", "TIMG12")
EVENT = re.compile(r"\bvns=(\d+)\s+kind=([A-Z_0-9]+)\s+a=(-?\d+)(?:\s+b=(-?\d+))?(?:\s+c=(-?\d+))?")
DEFAULT_CASES = ("sync-angle-090-repeat01", "sync-angle-090-repeat02")


def load(base: Path, case: str):
    meta_file = base / f"{case}.json"
    trace = base / f"{case}.p0.events.log"
    if not meta_file.is_file() or not trace.is_file():
        raise ValueError(f"Missing existing artifact(s) for {case}")
    meta = json.loads(meta_file.read_text())
    if (meta.get("native_dshot_scenario") or {}).get("dshot_frames") != 4820:
        raise ValueError(f"Unexpected DShot scenario duration: {case}")
    if meta.get("exception") or str(meta.get("status", "")).startswith("FAIL"):
        raise ValueError(f"Host probe was not successful: {case}")
    raw = []
    anchors = {}
    with trace.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            m = EVENT.search(line)
            if not m:
                continue
            ns, kind = int(m[1]), m[2]
            values = tuple(int(v) for v in m.groups()[2:] if v is not None)
            if kind == "DSHOT" and values and values[0] in (0, 1500, 3000):
                if values[0] in anchors:
                    raise ValueError(f"Duplicate DShot anchor {values[0]}: {case}")
                anchors[values[0]] = ns
            if kind in KINDS:
                raw.append((ns, kind, values))
    if set(anchors) != {0, 1500, 3000}:
        raise ValueError(f"Missing DShot anchors: {case} {anchors}")
    if abs((anchors[3000] - anchors[1500]) - 1500 * MS) > MS:
        raise ValueError(f"Unexpected DShot source interval: {case}")
    origin = anchors[1500]
    # Compare only the same control input interval in each run.
    events = [((ns-origin)/MS, kind, values)
              for ns, kind, values in raw if origin <= ns < anchors[3000]]
    return meta, anchors, events


def samples(events, kind, bin_ms):
    grouped = {}
    for t, k, values in events:
        if k != kind or not values:
            continue
        b = int(t // bin_ms)
        grouped.setdefault(b, []).append(values)
    return grouped


def rpm_by_bin(events, bin_ms):
    grouped = samples(events, "ROTOR", bin_ms)
    return {b: median(v[0]/1000.0 for v in vals)
            for b, vals in grouped.items()}


def first_mismatch(a, b, *, tolerance=25.0):
    for idx in sorted(set(a) | set(b)):
        if idx not in a or idx not in b:
            return idx, a.get(idx), b.get(idx)
        if abs(a[idx] - b[idx]) >= tolerance:
            return idx, a[idx], b[idx]
    return None


def event_counts(events, kind, bin_ms):
    return dict(Counter(int(t // bin_ms) for t, k, v in events if k == kind))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--case-a", default=DEFAULT_CASES[0])
    parser.add_argument("--case-b", default=DEFAULT_CASES[1])
    parser.add_argument("--bin-ms", type=int, default=50)
    args = parser.parse_args()
    if not 5 <= args.bin_ms <= 200:
        parser.error("--bin-ms must be 5..200")
    base = args.root.resolve() / "artifacts/issue5/startup-determinism"
    try:
        aa, anchor_a, ev_a = load(base, args.case_a)
        bb, anchor_b, ev_b = load(base, args.case_b)
        for field in ("original_elf_sha256", "requested_sim_bemf_waveform",
                      "requested_mcpwm_root_clock_hz", "motor_mode"):
            if aa.get(field) != bb.get(field):
                raise ValueError(f"Input differs: {field}")
        if (aa.get("native_dshot_scenario") or {}).get("sha256") != (
                bb.get("native_dshot_scenario") or {}).get("sha256"):
            raise ValueError("DShot scenarios differ")
        pa = ((aa.get("motor_before") or {}).get("effective_sim_motor_model"))
        pb = ((bb.get("motor_before") or {}).get("effective_sim_motor_model"))
        if pa != pb:
            raise ValueError("Initial motor plant parameters differ")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"INPUT_INVALID: {exc}")
    print(f"Compared: {args.case_a} vs {args.case_b}")
    print("DShot frame 0 virtual ms:",
          round(anchor_a[0]/MS,6), round(anchor_b[0]/MS,6))
    print("DShot frame 1500 virtual ms:",
          round(anchor_a[1500]/MS,6), round(anchor_b[1500]/MS,6))
    print("Aligned analysis interval: DShot frames 1500..2999")
    ra, rb = rpm_by_bin(ev_a, args.bin_ms), rpm_by_bin(ev_b, args.bin_ms)
    mismatch = first_mismatch(ra,rb)
    print(f"\nFirst {args.bin_ms}ms bin with >=25 RPM median difference:")
    if mismatch is None:
        print("  NONE (or no comparable data)")
    else:
        idx, a, b = mismatch
        print(f"  DShot-relative {idx * args.bin_ms}.."
              f"{(idx+1) * args.bin_ms} ms: "
              f"RPM A={None if a is None else round(a,2)}, "
              f"B={None if b is None else round(b,2)}")
    print(f"\nFirst {args.bin_ms}ms event-count differences:")
    for kind in ("PWM_PAIR", "CAP1", "TIMG12"):
        ca = event_counts(ev_a, kind, args.bin_ms)
        cb = event_counts(ev_b, kind, args.bin_ms)
        diff = first_mismatch(ca, cb, tolerance=1)
        print(f"  {kind}: "
              + ("none" if diff is None else
                 f"{diff[0]*args.bin_ms}..{(diff[0]+1)*args.bin_ms}ms "
                 f"A={diff[1] or 0} B={diff[2] or 0}"))
    print("\nFirst 8 observed events for each source (ms since first drive):")
    for kind in ("PWM_PAIR", "CAP1", "TIMG12"):
        print(f"  {kind}")
        for title, ev in (("A", ev_a), ("B", ev_b)):
            first = [(round(t,3), v) for t,k,v in ev if k==kind][:8]
            print("   ",title,first)
    print("\nRPM medians (ms after first 20% throttle):")
    print(f'{"range":>12} {"A":>11} {"B":>11}')
    for idx in range(0, 1500//args.bin_ms):
        if idx in ra or idx in rb:
            print(f'{idx*args.bin_ms:5}-{(idx+1)*args.bin_ms:<5} '
                  f'{str(round(ra[idx],2)) if idx in ra else "N/A":>11} '
                  f'{str(round(rb[idx],2)) if idx in rb else "N/A":>11}')
    print("\nNOTE: Earliest observed event divergence is not causal proof.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

