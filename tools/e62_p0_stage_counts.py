#!/usr/bin/env python3
"""Offline E62 P0 stage/event summary. Never touches QEMU or Guest state."""

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path
import statistics
import math
import bisect

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
    rotor_samples = defaultdict(list)
    pwm_pairs = defaultdict(list)
    pwm_pair_angles = defaultdict(lambda: defaultdict(list))
    pwm_pair_samples = defaultdict(list)
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
                    rotor_samples[stage].append((ev["vns"], ev["a"]))
                elif kind == "PWM_PAIR":
                    angle = ev["d"] / 1000.0
                    pwm_pairs[stage].append((ev["vns"], ev["a"], ev["b"]))
                    pwm_pair_angles[stage][ev["a"]].append(angle)
                    pwm_pair_samples[stage].append((ev["vns"], ev["a"], angle))
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
    print("PWM pair transition summary")
    for st in (1, 3):
        pairs = [pair for _, pair, _ in pwm_pairs[st]]
        trans = Counter(zip(pairs, pairs[1:]))
        top = ", ".join(
            f"{a}->{b}:{n}" for (a,b),n in trans.most_common(12)
        )
        prefix = ",".join(str(x) for x in pairs[:24])
        print(
            f"{STAGE_NAMES[st]:10s} first24=[{prefix}] "
            f"top_transitions=[{top}]"
        )

    print()
    print("PWM pair electrical-angle summary")
    for st in (1, 3):
        parts = []
        for pair in (8, 2, 3, 6, 4, 7):
            vals = pwm_pair_angles[st][pair]
            if not vals:
                continue
            sx = sum(math.cos(v) for v in vals)
            sy = sum(math.sin(v) for v in vals)
            mean = math.atan2(sy, sx)
            deg = (math.degrees(mean) + 360.0) % 360.0
            r = math.hypot(sx, sy) / len(vals)
            parts.append(f"{pair}:{deg:.1f}deg/R={r:.3f}")
        print(f"{STAGE_NAMES[st]:10s} " + " ".join(parts))

    if pwm_pair_angles[1] and pwm_pair_angles[3]:
        print("pair angle delta demand2-demand1")
        deltas = []
        for pair in (8, 2, 3, 6, 4, 7):
            a1 = pwm_pair_angles[1][pair]
            a2 = pwm_pair_angles[3][pair]
            if not a1 or not a2:
                continue
            m1 = math.atan2(sum(math.sin(v) for v in a1),
                            sum(math.cos(v) for v in a1))
            m2 = math.atan2(sum(math.sin(v) for v in a2),
                            sum(math.cos(v) for v in a2))
            d = math.degrees(math.atan2(math.sin(m2-m1), math.cos(m2-m1)))
            deltas.append(d)
            print(f"pair={pair} delta={d:.1f}deg")
        if deltas:
            print(f"mean_abs_delta={sum(abs(x) for x in deltas)/len(deltas):.1f}deg")

    print()
    print("demand2 normalized phase-lock timeline (100ms bins)")
    ref_angle = {}
    for pair in (8, 2, 3, 6, 4, 7):
        vals = pwm_pair_angles[1][pair]
        if vals:
            ref_angle[pair] = math.atan2(
                sum(math.sin(v) for v in vals),
                sum(math.cos(v) for v in vals))
    for begin_ms in range(3300, 4800, 100):
        end_ms = begin_ms + 100
        errs = []
        for vns, pair, angle in pwm_pair_samples[3]:
            ms = vns / 1e6
            if begin_ms <= ms < end_ms and pair in ref_angle:
                errs.append(math.atan2(
                    math.sin(angle-ref_angle[pair]),
                    math.cos(angle-ref_angle[pair])))
        rpm_vals = [
            rpm/1000.0 for vns, rpm in rotor_samples[3]
            if begin_ms <= vns/1e6 < end_ms
        ]
        if not errs and not rpm_vals:
            continue
        if errs:
            sx = sum(math.cos(e) for e in errs)
            sy = sum(math.sin(e) for e in errs)
            mean_err = math.degrees(math.atan2(sy, sx))
            lock_r = math.hypot(sx, sy) / len(errs)
            phase_text = (
                f"pairs={len(errs):4d} mean_err={mean_err:7.1f}deg "
                f"R={lock_r:.3f}"
            )
        else:
            phase_text = "pairs=   0 mean_err=      - R=-"
        if rpm_vals:
            rpm_text = (
                f"rpm mean={statistics.mean(rpm_vals):7.1f} "
                f"min={min(rpm_vals):7.1f} max={max(rpm_vals):7.1f}"
            )
        else:
            rpm_text = "rpm -"
        print(f"{begin_ms}..{end_ms}ms {phase_text} | {rpm_text}")

    print()
    print("demand2 first 24 pair phase errors")
    first_errors = []
    for vns, pair, angle in pwm_pair_samples[3][:24]:
        if pair not in ref_angle:
            continue
        err = math.degrees(math.atan2(
            math.sin(angle-ref_angle[pair]),
            math.cos(angle-ref_angle[pair])))
        first_errors.append(
            f"{vns/1e6:.3f}ms:{pair}:{err:+.1f}deg"
        )
    print(" ".join(first_errors))

    print()
    print("demand2 phase error by actual rotor direction")
    rotor_ts = [vns for vns, _ in rotor_samples[3]]
    rotor_rpm = [rpm/1000.0 for _, rpm in rotor_samples[3]]
    buckets = {
        "forward>50rpm": [],
        "near-zero": [],
        "reverse<-50rpm": [],
    }
    for vns, pair, angle in pwm_pair_samples[3]:
        if pair not in ref_angle or not rotor_ts:
            continue
        i = bisect.bisect_left(rotor_ts, vns)
        if i <= 0:
            j = 0
        elif i >= len(rotor_ts):
            j = len(rotor_ts)-1
        else:
            j = i if rotor_ts[i]-vns < vns-rotor_ts[i-1] else i-1
        rpm = rotor_rpm[j]
        err = math.atan2(
            math.sin(angle-ref_angle[pair]),
            math.cos(angle-ref_angle[pair]))
        if rpm > 50.0:
            buckets["forward>50rpm"].append(err)
        elif rpm < -50.0:
            buckets["reverse<-50rpm"].append(err)
        else:
            buckets["near-zero"].append(err)
    for name, errs in buckets.items():
        if not errs:
            print(f"{name:16s} n=0")
            continue
        sx = sum(math.cos(e) for e in errs)
        sy = sum(math.sin(e) for e in errs)
        mean_err = math.degrees(math.atan2(sy, sx))
        r = math.hypot(sx, sy) / len(errs)
        print(
            f"{name:16s} n={len(errs):4d} "
            f"mean_err={mean_err:7.1f}deg R={r:.3f}"
        )

    print()
    print("demand2 rotor/pair diagnostics")
    st = 3
    samples = rotor_samples[st]
    if samples:
        min_sample = min(samples, key=lambda x: x[1])
        max_sample = max(samples, key=lambda x: x[1])
        print(
            f"ROTOR max={max_sample[1]/1000:.1f}rpm "
            f"at={max_sample[0]/1e6:.3f}ms "
            f"min={min_sample[1]/1000:.1f}rpm "
            f"at={min_sample[0]/1e6:.3f}ms"
        )
        crossings = []
        prev = samples[0]
        for cur in samples[1:]:
            if (prev[1] < 0 <= cur[1]) or (prev[1] > 0 >= cur[1]):
                crossings.append((prev, cur))
            prev = cur
        print(f"ROTOR sign_crossings={len(crossings)}")
        for before, after in crossings[:12]:
            t = after[0]
            nearby = [
                pair for pair in pwm_pairs[st]
                if abs(pair[0] - t) <= 5_000_000
            ]
            seq = ",".join(str(pair[1]) for pair in nearby[-18:])
            print(
                f"cross at~{t/1e6:.3f}ms "
                f"{before[1]/1000:.1f}->{after[1]/1000:.1f}rpm "
                f"PWM_PAIR±5ms=[{seq}]"
            )
    else:
        print("no demand2 rotor samples")

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
