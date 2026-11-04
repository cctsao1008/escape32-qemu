#!/usr/bin/env python3
"""Offline E62 P0 stage/event summary. Never touches QEMU or Guest state."""

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path
import statistics

EVENT_RE = re.compile(
    r"E62_P0_EVENT seq=(?P<seq>\d+) vns=(?P<vns>-?\d+) "
    r"kind=(?P<kind>\S+) "
    r"a=(?P<a>-?\d+) b=(?P<b>-?\d+) c=(?P<c>-?\d+) "
    r"d=(?P<d>-?\d+) e=(?P<e>-?\d+) f=(?P<f>-?\d+)"
)
KINDS = ("CAP1", "CMP_FILTER", "PWM_PAIR", "ROTOR", "TIMG12")
STAGE_NAMES = {
    0: "neutral1",
    1: "demand1",
    2: "coast1",
    3: "demand2",
    4: "coast2",
}
REFRESH_KIND = {
    1: "EDGE",
    2: "ZERO",
    3: "SHADOW",
    4: "CLOCK",
    5: "GUEST_REG",
    6: "TRIP",
    7: "GATE",
    8: "INVALID",
}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path)
    args = ap.parse_args()

    stage = -1
    counts = defaultdict(Counter)
    first_vns = defaultdict(dict)
    last_vns = defaultdict(dict)
    event_vns = defaultdict(lambda: defaultdict(list))
    rotor_millirpm = defaultdict(list)
    late = []
    dshot_first = {}
    dshot_last = {}

    with args.log.open("r", errors="replace") as fh:
        for line in fh:
            m = EVENT_RE.search(line)
            if not m:
                continue
            ev = {k: int(m.group(k)) for k in ("seq","vns","a","b","c","d","e","f")}
            kind = m.group("kind")
            if kind == "DSHOT":
                stage = ev["b"]
                dshot_first.setdefault(stage, ev["a"])
                dshot_last[stage] = ev["a"]
            if kind in KINDS and stage >= 0:
                counts[stage][kind] += 1
                first_vns[stage].setdefault(kind, ev["vns"])
                last_vns[stage][kind] = ev["vns"]
                event_vns[stage][kind].append(ev["vns"])
                if kind == "ROTOR":
                    rotor_millirpm[stage].append(ev["a"])
            if kind == "PWM_HIST_LATE":
                late.append((stage, ev))

    print(f"{'stage':10s} {'frames':>11s} " +
          " ".join(f"{k:>12s}" for k in KINDS))
    for st in range(5):
        name = STAGE_NAMES[st]
        if st in dshot_first:
            frames = f"{dshot_first[st]}..{dshot_last[st]}"
        else:
            frames = "-"
        print(f"{name:10s} {frames:>11s} " +
              " ".join(f"{counts[st][k]:12d}" for k in KINDS))

    print()
    print("event windows (ms from scenario start)")
    for st in range(5):
        name = STAGE_NAMES[st]
        parts = []
        for kind in KINDS:
            if kind in first_vns[st]:
                parts.append(
                    f"{kind}={first_vns[st][kind]/1e6:.3f}.."
                    f"{last_vns[st][kind]/1e6:.3f}"
                )
        print(f"{name:10s} " + (" ".join(parts) if parts else "-"))

    print()
    print("motor/cadence summary")
    for st in range(5):
        name = STAGE_NAMES[st]
        rpm = rotor_millirpm[st]
        rpm_text = "-"
        if rpm:
            rpm_text = (
                f"ROTOR rpm first={rpm[0]/1000:.1f} "
                f"last={rpm[-1]/1000:.1f} "
                f"min={min(rpm)/1000:.1f} max={max(rpm)/1000:.1f}"
            )
        cadence = []
        for kind in ("CAP1", "PWM_PAIR", "TIMG12"):
            ts = event_vns[st][kind]
            if len(ts) >= 2:
                intervals_us = [(b-a)/1000.0 for a,b in zip(ts,ts[1:]) if b>a]
                if intervals_us:
                    med = statistics.median(intervals_us)
                    text = f"{kind} med_dt={med:.1f}us"
                    if kind == "CAP1" and med > 0:
                        text += f" (~{476190.0/med:.1f}rpm)"
                    cadence.append(text)
        print(f"{name:10s} {rpm_text}" +
              ((" | " + " | ".join(cadence)) if cadence else ""))

    print()
    print(f"PWM_HIST_LATE count={len(late)}")
    for st, ev in late:
        if 0 <= ev["a"] <= 8:
            # Legacy trace before register-tag instrumentation: field 'a'
            # contained only refresh_kind. Do not misdecode it as reg=0x005.
            refresh_code = ev["a"]
            reg_text = "legacy-unavailable"
        else:
            refresh_code = (ev["a"] >> 32) & 0xffffffff
            reg = ev["a"] & 0xffffffff
            reg_text = "-" if reg == 0xffffffff else f"0x{reg:03x}"
        rk = REFRESH_KIND.get(refresh_code, str(refresh_code))
        print(
            f"stage={STAGE_NAMES.get(st, str(st))} "
            f"vns={ev['vns']} refresh={rk} reg={reg_text} "
            f"now_ctr={ev['b']} target={ev['c']} base={ev['d']} "
            f"late_ns={ev['e']} zero_events={ev['f']}"
        )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
