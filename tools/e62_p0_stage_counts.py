#!/usr/bin/env python3
"""Offline E62 P0 stage/event summary. Never touches QEMU or Guest state."""

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

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
    print(f"PWM_HIST_LATE count={len(late)}")
    for st, ev in late:
        rk = REFRESH_KIND.get(ev["a"], str(ev["a"]))
        print(
            f"stage={STAGE_NAMES.get(st, str(st))} "
            f"vns={ev['vns']} refresh={rk} "
            f"now_ctr={ev['b']} target={ev['c']} base={ev['d']} "
            f"late_ns={ev['e']} zero_events={ev['f']}"
        )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
