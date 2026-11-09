#!/usr/bin/env python3
"""Source-built AM13E BEMF filter expanded motor SITL matrix (EXPERIMENT ONLY).

Runs unchanged independent DShot scenarios and original strict P1 analyzer.
The source-built ELF MUST retain Original Rel17.3's SHA identity rejection.
All non-SHA mechanical/observability failures are preserved, never waived.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_SHA = "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
FILTER_SHA = "5b90b200429333cef82b982b7a7f845f31fb885c7ea63fc7e783c75232fac8d1"
SOURCE_SHA = "3ea4e672c0770db10c936531e7b3420b09473b18"
SHA_GUARD = "ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN"
SCENARIOS = {
    "smoke": "scenarios/e62-native-p0-smoke.json",
    "gentle": "scenarios/e62-native-p0-gentle.json",
    "direct20": "scenarios/e62-native-p0-direct20.json",
    "steps": "scenarios/e62-native-p0-steps.json",
    "ramp20_100ms": "scenarios/e62-native-p1-ramp20-100ms.json",
    "ramp20_500ms": "scenarios/e62-native-p1-ramp20-500ms.json",
}
SOURCE_STRESS = re.compile(
    r"E62_BEMF_STRESS_DIAG vns=(\d+) a=(-?\d+) b=(-?\d+) "
    r"c=(-?\d+) d=(-?\d+) e=(-?\d+) f=(\d+)"
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def invoke(argv, path, timeout):
    with path.open("w") as output:
        try:
            return subprocess.run(argv, cwd=ROOT, stdout=output,
                                  stderr=subprocess.STDOUT, timeout=timeout,
                                  check=False).returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            output.write(type(exc).__name__ + ": " + str(exc) + "\n")
            return 124


def analyze_case(args, name, candidate_sha):
    prefix = args.output / ("e62-filter-source-" + name)
    evidence = prefix.with_suffix(".json")
    events = Path(str(prefix) + ".p0.events.log")
    strict = Path(str(prefix) + ".strict-original-p1.json")
    qemu_log = prefix.with_suffix(".qemu.log")
    scenario = ROOT / SCENARIOS[name]
    probe = [
        sys.executable, str(ROOT / "tests/e62_autonomous_native_motor_probe.py"),
        "--qemu", str(args.qemu.resolve()),
        "--elf", str(args.candidate.resolve()),
        "--experimental-candidate-sha256", candidate_sha,
        "--cfg-flash", str(args.cfg.resolve()),
        "--scenario", str(scenario.resolve()),
        "--artifact", str(evidence.resolve()),
        "--wall-timeout-s", str(args.wall_timeout_s),
    ]
    if args.stress != "off":
        probe.append("--experimental-bemf-robustness=" + args.stress)
    rc = invoke(probe, Path(str(prefix) + ".probe.stdout.log"),
                args.wall_timeout_s + 30)
    analysis_rc = 127
    if evidence.exists() and events.exists():
        analysis_rc = invoke([
            sys.executable, str(ROOT / "tools/native_p1_qualification.py"),
            "--scenario", str(scenario.resolve()),
            "--evidence", str(evidence.resolve()),
            "--events", str(events.resolve()),
            "--output", str(strict.resolve())
        ], Path(str(prefix) + ".strict.stdout.log"), 60)
    report = json.loads(strict.read_text()) if strict.exists() else {}
    ev = json.loads(evidence.read_text()) if evidence.exists() else {}
    failures = report.get("unwaived_observability_failures", [])
    if not isinstance(failures, list):
        failures = ["INVALID_OR_MISSING_INPUT"]
    source_events = 0
    noise_events = 0
    if qemu_log.exists():
        with qemu_log.open(errors="replace") as f:
            for line in f:
                m = SOURCE_STRESS.search(line)
                if m:
                    source_events += 1
                    if int(m.group(6)):
                        noise_events += 1
    required_spike = int(args.stress.split(":")[1]) if args.stress != "off" else 0
    required_stress = (
        (source_events == 0 if args.stress == "off" else
         source_events > 0 and (required_spike == 0 or noise_events > 0))
    )
    sha_guard_held = SHA_GUARD in failures
    non_sha_failures = [x for x in failures if x != SHA_GUARD]
    legitimate = (
        rc == 0 and analysis_rc == 1 and sha_guard_held and
        ev.get("original_elf_sha256") == candidate_sha and
        ev.get("experimental_candidate_not_original") is True and
        ev.get("host_guest_register_writes") is False and
        ev.get("used_guest_wfi_or_gdb") is False and
        ev.get("synthetic_timed_bemf_enabled") is False and
        ev.get("readable_original_guest_diagnostics") and
        ev.get("experimental_bemf_robustness") ==
            (None if args.stress == "off" else args.stress) and
        required_stress
    )
    counts = {key: report.get(key, 0) for key in (
        "source_guest_closed_loop_pwm_pairs",
        "source_guest_cap1_w1c_ack",
        "source_guest_timg12_w1c_ack",
    )}
    closed_loop = bool(legitimate and not non_sha_failures and
        report.get("active_speed_signs_above_50rpm") == [1] and
        report.get("significant_rotor_direction_changes") == 0 and
        all(isinstance(v, int) and v >= 12 for v in counts.values()))
    result = {
        "case": name, "stress": args.stress,
        "status": "PASS_EXPERIMENTAL_ONLY" if closed_loop else "FAIL_EXPERIMENT",
        "source_sha256": SOURCE_SHA, "guest_elf_sha256": candidate_sha,
        "original_p1_qualified": False, "hardware_qualified": False,
        "source_scenario_sha256": sha256(scenario),
        "probe_exit_code": rc, "strict_p1_exit_code": analysis_rc,
        "original_sha_guard_held": sha_guard_held,
        "non_sha_failures": non_sha_failures,
        "source_stress_events": source_events,
        "source_switching_noise_events": noise_events,
        "source_stress_proven": required_stress,
        "motor_reversals": report.get("significant_rotor_direction_changes"),
        "speed_signs": report.get("active_speed_signs_above_50rpm"),
        "peak_abs_rpm": report.get("peak_abs_rpm_in_positive_window"),
        "counts": counts,
        "non_sha_closed_loop_pass": closed_loop,
        "artifacts": {"evidence": str(evidence),
                      "strict": str(strict), "events": str(events),
                      "qemu_log": str(qemu_log)},
    }
    print("E62_SOURCE_FILTER_MATRIX_CASE " + json.dumps(result, sort_keys=True), flush=True)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--original", type=Path, required=True)
    p.add_argument("--cfg", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--case", action="append", choices=list(SCENARIOS), required=True)
    p.add_argument("--stress", default="off")
    p.add_argument("--wall-timeout-s", type=int, default=300)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    if sha256(a.original) != ORIGINAL_SHA or sha256(a.candidate) != FILTER_SHA:
        p.error("Immutable Original or pinned source-built filter ELF SHA mismatch")
    if a.stress != "off":
        m = re.fullmatch(r"(-?\d{1,2}):(\d{1,2})", a.stress)
        if not m:
            p.error("Invalid experimental analog-source perturbation syntax")
        offset, spike = map(int, m.groups())
        if abs(offset) > 24 or spike > 32 or not (offset or spike):
            p.error("Out-of-contract analog source perturbation")
    results = [analyze_case(a, case, FILTER_SHA) for case in dict.fromkeys(a.case)]
    summary = {
        "schema": "e62.source-built.stable-filter.matrix.v1",
        "classification": "EXPERIMENTAL_NOT_ORIGINAL_P1_OR_HARDWARE",
        "source_commit": SOURCE_SHA,
        "candidate_sha256": FILTER_SHA,
        "original_sha256": ORIGINAL_SHA,
        "stress": a.stress,
        "formal_original_p1_qualified": False,
        "hardware_qualified": False,
        "unmodified_strict_p1_analyzer": True,
        "cases": results,
        "all_non_sha_cases_pass": all(x["non_sha_closed_loop_pass"] for x in results),
    }
    destination = a.output / "e62-source-filter-matrix-summary.json"
    destination.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print("E62_SOURCE_FILTER_MATRIX_SUMMARY " + json.dumps(
        {"source": str(destination),
         "results": [[x["case"], x["non_sha_closed_loop_pass"],
                      x["non_sha_failures"]] for x in results]}, sort_keys=True),
        flush=True)
    return 0 if summary["all_non_sha_cases_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
