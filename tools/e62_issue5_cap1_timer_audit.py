"""E62 #5: correlate native QEMU CAP1 handling with Guest-owned TIMG12 programming.

Reads the actual E62_P0_EVENT source log. A CAP1 with CAP1_ACK and
ECAP1_CAP1_READ but no T12_LOAD/START before the next CAP1 is classified
READ_WITHOUT_TIMER_PROGRAMMING, not automatically as firmware 'rejected':
the ISR can exit for several reasons. No host guest-register writes.
"""
import argparse
import json
import re
from pathlib import Path

EVENT = re.compile(r"E62_P0_EVENT\s+seq=(\d+)\s+vns=(\d+)\s+kind=(\w+)\s+(.*)")
ARG = re.compile(r"([abcdef])=(-?\d+)")


def parse(text):
    rows = []
    for line in text.splitlines():
        m = EVENT.search(line)
        if m:
            fields = {k: int(v) for k, v in ARG.findall(m[4])}
            rows.append({"seq": int(m[1]), "vns": int(m[2]),
                         "kind": m[3], **fields})
    if not rows or any(rows[i]["vns"] < rows[i - 1]["vns"] for i in range(1, len(rows))):
        raise ValueError("source events missing or time disordered")
    return rows


def classify(events, start_ns, end_ns):
    src = [e for e in events if start_ns <= e["vns"] <= end_ns]
    out = []
    for i, e in enumerate(src):
        if e["kind"] != "CAP1":
            continue
        next_cap = next((j for j in range(i + 1, len(src))
                         if src[j]["kind"] == "CAP1"), len(src))
        segment = src[i + 1:next_cap]
        ack = any(x["kind"] == "CAP1_ACK" for x in segment)
        read = any(x["kind"] == "ECAP1_CAP1_READ" for x in segment)
        load = next((x for x in segment if x["kind"] == "T12_LOAD"), None)
        start = next((x for x in segment if x["kind"] == "T12_START"), None)
        state = ("NO_CAPTURE_ACK_OR_READ" if not (ack and read) else
                 "READ_AND_TIMER_PROGRAMMED" if load and start else
                 "READ_WITHOUT_TIMER_PROGRAMMING" if not load and not start else
                 "INCOMPLETE_TIMER_PROGRAMMING")
        out.append({"cap1_ns": e["vns"], "phase": e.get("b"),
                    "ack": ack, "read": read, "timer_load_ns": load["vns"] if load else None,
                    "timer_start_ns": start["vns"] if start else None,
                    "classification": state})
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("log", type=Path)
    p.add_argument("--begin-ms", type=float, default=1508.0)
    p.add_argument("--end-ms", type=float, default=1513.0)
    a = p.parse_args()
    if a.end_ms <= a.begin_ms:
        p.error("invalid window")
    rows = classify(parse(a.log.read_text()), int(a.begin_ms * 1e6),
                    int(a.end_ms * 1e6))
    if not rows:
        p.error("no CAP1 in window")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
