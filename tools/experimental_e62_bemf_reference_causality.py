#!/usr/bin/env python3
"""E62 SIM_ONLY BEMF reference mismatch causal A/B, never board calibration.

Both Guest ELFs are source-built from exactly the same pinned source and differ
only in the SIM_ONLY board macro that seeds the initial DAC. The native motor
physics / BEMF perturbation / Original strict P1 analyzer are never changed.
This deliberately tests a model-relative 16-code bias, NOT a production DAC.
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
ORIGINAL = "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
SHA_GUARD = "ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN"
SCENARIO = {
    "direct20": "scenarios/e62-native-p0-direct20.json",
    "steps": "scenarios/e62-native-p0-steps.json",
    "ramp20_100ms": "scenarios/e62-native-p1-ramp20-100ms.json",
}

def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def command(argv, out, timeout):
    with out.open("w") as fp:
        try:
            return subprocess.run(argv, cwd=ROOT, stdout=fp, stderr=subprocess.STDOUT,
                                  check=False, timeout=timeout).returncode
        except (OSError, subprocess.TimeoutExpired) as e:
            fp.write(f"{type(e).__name__}: {e}\n")
            return 124

def run_case(a, label, elf, stress, scenario_name, exact_sha):
    prefix = a.output / f"{scenario_name}-{label}"
    artifact = prefix.with_suffix(".json")
    scenario = ROOT / SCENARIO[scenario_name]
    probe = [
        sys.executable, str(ROOT / "tests/e62_autonomous_native_motor_probe.py"),
        "--qemu", str(a.qemu.resolve()),
        "--elf", str(elf.resolve()),
        "--experimental-candidate-sha256", exact_sha,
        "--cfg-flash", str(a.cfg.resolve()),
        "--scenario", str(scenario.resolve()),
        "--artifact", str(artifact.resolve()),
        "--experimental-bemf-robustness=" + stress,
        "--wall-timeout-s", str(a.wall_timeout_s),
    ]
    rc = command(probe, Path(str(prefix)+".probe.stdout.log"), a.wall_timeout_s+30)
    verdict = Path(str(prefix)+".strict-original-p1.json")
    event_path = Path(str(prefix)+".p0.events.log")
    strict_rc = 127
    if artifact.exists() and event_path.exists():
        strict_rc = command([
            sys.executable, str(ROOT/"tools/native_p1_qualification.py"),
            "--scenario", str(scenario.resolve()),
            "--evidence", str(artifact.resolve()),
            "--events", str(event_path.resolve()),
            "--output", str(verdict.resolve())
        ], Path(str(prefix)+".strict.stdout.log"), 60)
    ev = json.loads(artifact.read_text()) if artifact.exists() else {}
    report = json.loads(verdict.read_text()) if verdict.exists() else {}
    failures = report.get("unwaived_observability_failures", [])
    if not isinstance(failures, list):
        failures = ["MISSING_FAIL_LIST"]
    diagnostics = 0
    logpath = prefix.with_suffix(".qemu.log")
    if logpath.exists():
        with logpath.open(errors="replace") as f:
            for line in f:
                if "E62_BEMF_STRESS_DIAG " in line:
                    diagnostics += 1
    original_rejected = SHA_GUARD in failures
    provenance = (
        rc == 0 and strict_rc == 1 and original_rejected and diagnostics > 0
        and ev.get("original_elf_sha256") == exact_sha
        and ev.get("experimental_candidate_not_original") is True
        and ev.get("host_guest_register_writes") is False
        and ev.get("used_guest_wfi_or_gdb") is False
        and ev.get("synthetic_timed_bemf_enabled") is False
        and ev.get("experimental_bemf_robustness") == stress
        and bool(ev.get("readable_original_guest_diagnostics"))
    )
    counts = {k: report.get(k, 0) for k in (
        "source_guest_closed_loop_pwm_pairs",
        "source_guest_cap1_w1c_ack",
        "source_guest_timg12_w1c_ack"
    )}
    non_sha = [k for k in failures if k != SHA_GUARD]
    motor_pass = (provenance and not non_sha and
                  report.get("significant_rotor_direction_changes") == 0 and
                  report.get("active_speed_signs_above_50rpm") == [1] and
                  all(isinstance(v,int) and v >= 12 for v in counts.values()))
    return {
        "name":scenario_name, "label":label, "elf_sha256":exact_sha,
        "strict_original_p1_qualified": False,
        "hardware_qualified": False,
        "source_stress_code":stress,
        "original_identity_rejected":original_rejected,
        "source_stress_events":diagnostics, "source_provenance_valid":bool(provenance),
        "motor_reversals":report.get("significant_rotor_direction_changes"),
        "speed_signs":report.get("active_speed_signs_above_50rpm"),
        "non_sha_failures":non_sha, "source_counts":counts,
        "probe_exit_code":rc, "strict_exit_code":strict_rc,
        "non_sha_motor_pass":bool(motor_pass),
    }

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--qemu",type=Path,required=True)
    p.add_argument("--control-elf",type=Path,required=True)
    p.add_argument("--matched-elf",type=Path,required=True)
    p.add_argument("--original-elf",type=Path,required=True)
    p.add_argument("--cfg",type=Path,required=True)
    p.add_argument("--source-commit",required=True)
    p.add_argument("--stress",choices=["16:0","-16:0"],required=True)
    p.add_argument("--case",action="append",choices=list(SCENARIO),required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--wall-timeout-s",type=int,default=300)
    a=p.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}",a.source_commit):
        p.error("Source commit must be pinned 40-hex")
    hashes = {k:sha256(v) for k,v in [
        ("original",a.original_elf),("control",a.control_elf),("matched",a.matched_elf)]}
    if hashes["original"]!=ORIGINAL or len(set(hashes.values()))!=3:
        p.error("Original and both experimental ELFs need distinct pinned identities")
    if sha256(a.qemu)=="":
        p.error("Missing physical QEMU identity")
    a.output.mkdir(parents=True,exist_ok=True)
    results=[]
    for name in dict.fromkeys(a.case):
        for label,elf in (("control",a.control_elf),("matched",a.matched_elf)):
            x=run_case(a,label,elf,a.stress,name,hashes[label])
            results.append(x)
            print("E62_REFERENCE_CAUSAL_CASE "+json.dumps(x,sort_keys=True),flush=True)
    invalid=[x for x in results if not x["source_provenance_valid"]]
    control=[x for x in results if x["label"]=="control"]
    matched=[x for x in results if x["label"]=="matched"]
    # Preserve the true mechanical verdict without making 2048 vs matched
    # comparison a production qualification. We require one distinct
    # failing control; a universally green control does NOT prove causality.
    observed_bias_effect = bool(
        not invalid and any(not x["non_sha_motor_pass"] for x in control)
        and any(x["non_sha_motor_pass"] for x in matched))
    payload={
        "schema":"e62.exp.synthetic-reference-causality.v1",
        "classification":("VALID_CAUSAL_DIAGNOSTIC_ONLY" if observed_bias_effect
                          else "NO_PROVEN_CAUSAL_RECOVERY"),
        "source_commit":a.source_commit,"original_elf_sha256":hashes["original"],
        "control_elf_sha256":hashes["control"],
        "matched_elf_sha256":hashes["matched"],
        "native_qemu_sha256":sha256(a.qemu),
        "stress":a.stress,
        "synthetic_reference_adjustment_only":True,
        "hardware_calibration_established":False,
        "p1_qualified":False,"hardware_qualified":False,
        "cases":results,
    }
    (a.output/"e62-reference-causality-summary.json").write_text(
        json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print("E62_REFERENCE_CAUSAL_SUMMARY "+json.dumps({
        "classification":payload["classification"],
        "observed_cases":[[x["name"],x["label"],x["motor_reversals"],
                          x["non_sha_motor_pass"]] for x in results]
    },sort_keys=True),flush=True)
    # Exit RED on invalid evidence; control-vs-matched improvement remains
    # an experiment observation, not an automatic release gate PASS.
    return 1 if invalid else 0

if __name__=="__main__":
    raise SystemExit(main())
