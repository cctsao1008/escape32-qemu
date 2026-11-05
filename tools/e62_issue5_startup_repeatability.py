#!/usr/bin/env python3
"""P0 startup repeatability diagnostic; unchanged AM13E Guest and motor plant.

Uses existing native autonomous probe in synchronized *initial* start mode.
QEMU is paused only before its first Guest instruction; the independent
external DShot source is prearmed and then QMP resumes once. No Guest
writes/breakpoints during motor operation. Never confers hardware/P1 signoff.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from statistics import median

ELF_SHA = "c49a7485af218966a2e3ec764de8d997d8ba478954dcad42b88c0c99e4f3c003"
CFG_SHA = "77366cfe9f0632b795a72393f7f0e990a99e8af92429cbb82d42bbb3f7c8ed4b"
SCENARIO_SHA = "3e1e5ed4b352fecbba79977b84fae507f85b2649d846469abd0451b44fda5184"
ANGLES = (-90, -30, 0, 90)
REPEATS = 2
EV = re.compile(r"\bvns=(\d+)\s+kind=(DSHOT|ROTOR|CAP1|TIMG12|PWM_PAIR)\s+a=(-?\d+)")
MS = 1_000_000


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def paths(root: Path) -> dict[str, Path]:
    return {
        "elf": Path.home() / "my-github/ESCape32-issue5-runtime-ref/build-issue5/AM13E-rev17.3.elf",
        "cfg": root / "artifacts/issue5/ztc-ab/B-ztc1-damp1.cfg.bin",
        "scenario": root / "artifacts/issue5/ztc-robustness/scenario-coast020.json",
        "qemu": root / ".build/qemu-src/build/qemu-system-arm",
        "probe": root / "tests/e62_autonomous_native_motor_probe.py",
        "out": root / "artifacts/issue5/startup-determinism",
    }


def check_inputs(p: dict[str, Path]) -> None:
    for key in ("elf", "cfg", "scenario", "qemu", "probe"):
        if not p[key].is_file():
            raise ValueError(f"Missing input: {key}={p[key]}")
    for key, expected in (("elf", ELF_SHA), ("cfg", CFG_SHA),
                          ("scenario", SCENARIO_SHA)):
        observed = sha256(p[key])
        if observed != expected:
            raise ValueError(f"SHA mismatch {key}: {observed}")
    cfg = p["cfg"].read_bytes()
    if len(cfg) <= 40 or cfg[21] != 1 or cfg[40] != 1:
        raise ValueError("Reference CFG is not DAMP=1 THROT_ZTC=1")
    scenario = json.loads(p["scenario"].read_text())
    stages = scenario.get("stages")
    if not isinstance(stages, list) or [
        (s.get("duration_ms"), s.get("permille")) for s in stages
    ] != [(1500, 0), (1500, 200), (20, 0), (1500, 200), (300, 0)]:
        raise ValueError("Unexpected DShot scenario contract")


def case_name(angle: int, run: int) -> str:
    return f"sync-angle{angle:+04d}-repeat{run:02d}"


def command(p: dict[str, Path], artifact: Path, angle: int) -> list[str]:
    return [
        sys.executable, str(p["probe"]),
        "--qemu", str(p["qemu"]), "--elf", str(p["elf"]),
        "--experimental-candidate-sha256", ELF_SHA,
        "--cfg-flash", str(p["cfg"]),
        "--scenario", str(p["scenario"]),
        "--sim-mcpwm-root-clock-hz", "200000000",
        "--sim-bemf-waveform", "historical_sine",
        "--sim-motor-profile", "ecx87-kv210-47v-no-prop",
        "--sim-native-adc-bemf",
        "--sim-initial-electrical-degrees", str(angle),
        "--switch-focus-window-ms", "2995:3040",
        "--differential-sync-start",
        "--wall-timeout-s", "600",
        "--artifact", str(artifact),
    ]


def extract(path: Path) -> dict:
    data = json.loads(path.read_text())
    trace = path.with_suffix(".p0.events.log")
    if not trace.is_file():
        raise ValueError("Event trace not found")
    anchors = {}
    rotor = []
    counts = {"CAP1": 0, "TIMG12": 0, "PWM_PAIR": 0}
    events = []
    with trace.open(errors="replace") as f:
        for line in f:
            m = EV.search(line)
            if not m:
                continue
            ns, kind, av = int(m[1]), m[2], int(m[3])
            if kind == "DSHOT" and av in (0, 1500, 3000, 3020, 4520):
                if av in anchors:
                    raise ValueError(f"Duplicate DShot anchor frame {av}")
                anchors[av] = ns
            elif kind == "ROTOR":
                rotor.append((ns, av / 1000.0))
            elif kind in counts:
                events.append((ns, kind))
    if set(anchors) != {0, 1500, 3000, 3020, 4520}:
        raise ValueError(f"Missing DShot anchors: {anchors.keys()}")
    start = anchors[3000]
    beginning = anchors[1500]
    for ns, kind in events:
        if beginning <= ns < start:
            counts[kind] += 1

    def med(lo, hi):
        vals = [r for ns, r in rotor if lo <= ns < hi]
        return round(median(vals), 3) if vals else None

    motor = data.get("native_motor") or {}
    auto = data.get("autonomous_dshot") or {}
    before = data.get("motor_before") or {}
    model = before.get("effective_sim_motor_model") or {}
    guest = data.get("original_guest_after") or {}
    expected_angle = int(re.search(r"angle([+-]\d+)", path.stem)[1])
    if model.get("configured_initial_electrical_mdeg") != expected_angle * 1000:
        raise ValueError("Motor initial electrical angle differs from requested")
    if data.get("original_elf_sha256") != ELF_SHA:
        raise ValueError("Guest ELF identity differs from pinned input")
    if (data.get("native_dshot_scenario") or {}).get("sha256") != SCENARIO_SHA:
        raise ValueError("DShot scenario differs from pinned input")
    valid = (
        auto.get("sent") == data.get("configured_dshot_frames") == 4820
        and motor.get("model_fault") == 0
        and data.get("wiring_failure_reasons") == []
        and data.get("receiver_failure_reasons") == []
        and not data.get("exception")
        and not str(data.get("status", "")).startswith("FAIL")
    )
    return {
        "case": path.stem, "host_status": data.get("status"),
        "host_exception": data.get("exception"),
        "runtime_integrity": "PASS" if valid else "FAIL_OR_INCONCLUSIVE",
        "dshot_t0_ms": round(anchors[0] / MS, 6),
        "dshot_coast_ms": round(start / MS, 6),
        "dshot_stage2_spacing_ms": round((start - beginning) / MS, 6),
        "d1_1800_1900_rpm": med(start - 1200 * MS, start - 1100 * MS),
        "d1_2300_2400_rpm": med(start - 700 * MS, start - 600 * MS),
        "d1_2800_3000_rpm": med(start - 200 * MS, start),
        "d1_pwm_pairs": counts["PWM_PAIR"],
        "d1_cap1_events": counts["CAP1"],
        "d1_timg12_events": counts["TIMG12"],
        "guest_captured_events_total": guest.get("captured_events"),
        "guest_scheduled_total": guest.get("scheduled"),
        "guest_serviced_total": guest.get("serviced"),
        "guest_runtime_pwm_updates_total": guest.get("runtime_pwm_updates"),
    }


def summarize(p: dict[str, Path]) -> int:
    print(f'{"CASE":28} {"STATUS":21} {"D1RPM":>8} {"CAP1":>7} {"T12":>7} {"PAIRS":>7}')
    rows = []
    for angle in ANGLES:
        for repeat in range(1, REPEATS + 1):
            label = case_name(angle, repeat)
            file = p["out"] / f"{label}.json"
            if not file.is_file():
                row = {"case": label, "runtime_integrity": "MISSING"}
            else:
                try:
                    row = extract(file)
                except (ValueError, KeyError, TypeError, IndexError) as exc:
                    row = {"case": label, "runtime_integrity": "ANALYSIS_INVALID",
                           "error": f"{type(exc).__name__}: {exc}"}
            rows.append(row)
            print(f'{label:28} {row["runtime_integrity"]:21} '
                  f'{str(row.get("d1_2800_3000_rpm")):>8} '
                  f'{str(row.get("d1_cap1_events")):>7} '
                  f'{str(row.get("d1_timg12_events")):>7} '
                  f'{str(row.get("d1_pwm_pairs")):>7}')
    print("\nWithin-angle D1 RPM repeat spread:")
    for angle in ANGLES:
        vals = [x.get("d1_2800_3000_rpm") for x in rows
                if x["case"].startswith(f"sync-angle{angle:+04d}")
                and x.get("runtime_integrity") == "PASS"
                and x.get("d1_2800_3000_rpm") is not None]
        print(f'  {angle:+4d} deg: {vals}, spread={round(max(vals)-min(vals),3) if len(vals)==REPEATS else "N/A"}')
    return 0 if all(x.get("runtime_integrity") == "PASS" for x in rows) else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--summarize", action="store_true")
    a = parser.parse_args()
    root = a.root.expanduser().resolve()
    p = paths(root)
    if a.summarize:
        return summarize(p)
    try:
        check_inputs(p)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"INPUT_INVALID: {exc}")
    print("CHECK PASS: pinned ELF, CFG and DShot scenario verified")
    print("QEMU binary:", p["qemu"])
    print("QEMU SHA256:", sha256(p["qemu"]))
    if a.check:
        return 0
    p["out"].mkdir(parents=True, exist_ok=True)
    for angle in ANGLES:
        for repeat in range(1, REPEATS + 1):
            label = case_name(angle, repeat)
            artifact = p["out"] / f"{label}.json"
            stdout = p["out"] / f"{label}.stdout.log"
            if artifact.exists():
                print("SKIP existing", label, flush=True)
                continue
            print("RUN", label, flush=True)
            try:
                with stdout.open("w") as f:
                    result = subprocess.run(
                        command(p, artifact, angle), cwd=root,
                        stdout=f, stderr=subprocess.STDOUT, timeout=660)
                if result.returncode:
                    print("PROBE_ERROR", label, "exit", result.returncode,
                          flush=True)
            except subprocess.TimeoutExpired:
                print("PROBE_TIMEOUT", label, flush=True)
    return summarize(p)


if __name__ == "__main__":
    raise SystemExit(main())

