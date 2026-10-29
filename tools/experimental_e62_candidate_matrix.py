#!/usr/bin/env python3
"""E62 experimental 3-instruction BEMF candidate: six unchanged input scenarios.

Strict ORIGINAL Rel17 P1 entrypoints, gate thresholds and scenario fixtures
remain unchanged and keep their original-SHA provenance requirement.
Each experimental run is **explicitly a non-original-Guest diagnostic**.
The original strict analyzer is run unchanged and is EXPECTED to reject
the candidate's ELF SHA as "ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN".
We preserve all original failures, without presenting a candidate as P1 PASS.
All QEMU source events are physical, with no host Guest MMIO writes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE_PATCHED_SHA=None
EXPECTED_ORIGINAL="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
SCENARIOS={
    "smoke":"scenarios/e62-native-p0-smoke.json",
    "gentle":"scenarios/e62-native-p0-gentle.json",
    "direct20":"scenarios/e62-native-p0-direct20.json",
    "steps":"scenarios/e62-native-p0-steps.json",
    "ramp20_100ms":"scenarios/e62-native-p1-ramp20-100ms.json",
    "ramp20_500ms":"scenarios/e62-native-p1-ramp20-500ms.json",
}


def sha256(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def invoke(argv,log,timeout):
    with log.open("w") as output:
        try:
            return subprocess.run(argv,stdout=output,stderr=subprocess.STDOUT,
                                  cwd=ROOT,timeout=timeout,check=False).returncode
        except (OSError,subprocess.TimeoutExpired) as exc:
            output.write(type(exc).__name__+": "+str(exc)+"\n")
            return 124


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate",type=Path,required=True)
    p.add_argument("--original",type=Path,required=True)
    p.add_argument("--patch-proof",type=Path,required=True)
    p.add_argument("--qemu",type=Path,required=True)
    p.add_argument("--cfg",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--case",action="append",choices=list(SCENARIOS),required=True)
    p.add_argument("--bemf-robustness",default=None,
                   help="EXPERIMENT ONLY: bounded OFFSET:SWITCH_CODE; "
                        "requires real upstream analog stress source evidence")
    p.add_argument("--wall-timeout-s",type=int,default=300)
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    original_sha=sha256(a.original)
    candidate_sha=sha256(a.candidate)
    proof=json.loads(a.patch_proof.read_text())
    if a.bemf_robustness is not None:
        import re
        mo=re.fullmatch(r"(-?[0-9]{1,2}):([0-9]{1,2})",a.bemf_robustness)
        if mo is None:
            p.error("Invalid opt-in BEMF stress syntax")
        offset,spike=map(int,mo.groups())
        if abs(offset)>24 or spike>32 or not (offset or spike):
            p.error("BEMF stress exceeds deterministic bounds")
    else:
        offset=spike=0
    if (original_sha!=EXPECTED_ORIGINAL or
        proof["original_sha256"]!=EXPECTED_ORIGINAL or
        proof["candidate_sha256"]!=candidate_sha or
        proof["changed_instructions"]!=3 or
        candidate_sha==EXPECTED_ORIGINAL or
        not proof["unchanged_timeout_reset"]):
        p.error("Exact original/experimental candidate diff not proven")
    results=[]
    for case in dict.fromkeys(a.case):
        prefix=a.output/("e62-exp-matrix-"+case)
        evidence=a.output/("e62-exp-matrix-"+case+".json")
        events=a.output/("e62-exp-matrix-"+case+".p0.events.log")
        strict=a.output/("e62-exp-matrix-"+case+".strict-original-p1.json")
        scenario=ROOT/SCENARIOS[case]
        probe=[
            sys.executable,str(ROOT/"tests/e62_autonomous_native_motor_probe.py"),
            "--qemu",str(a.qemu.resolve()),
            "--elf",str(a.candidate.resolve()),
            "--experimental-candidate-sha256",candidate_sha,
            "--cfg-flash",str(a.cfg.resolve()),
            "--scenario",str(scenario),
            "--artifact",str(evidence),
            "--wall-timeout-s",str(a.wall_timeout_s),
        ]
        if a.bemf_robustness is not None:
            probe.append("--experimental-bemf-robustness="+a.bemf_robustness)
        probe_rc=invoke(probe,prefix.with_suffix(".probe.stdout.log"),
                        a.wall_timeout_s+30)
        if evidence.exists() and events.exists():
            qualify=[
                sys.executable,str(ROOT/"tools/native_p1_qualification.py"),
                "--scenario",str(scenario),
                "--evidence",str(evidence),
                "--events",str(events),
                "--output",str(strict),
            ]
            qual_rc=invoke(qualify,prefix.with_suffix(".strict.stdout.log"),60)
        else:
            qual_rc=127
        report=None
        if strict.exists():
            try: report=json.loads(strict.read_text())
            except (OSError,ValueError): pass
        failures=(report or {}).get("unwaived_observability_failures",[])
        analog_stress_count=0
        switch_noise_events=0
        # Diagnostic records are deliberately NOT a strict P1 event kind;
        # they live in the full QEMU stderr source, and the legacy
        # E62_P0_EVENT parser remains unchanged and fail-closed.
        qemu_diag=evidence.with_suffix(".qemu.log")
        if qemu_diag.exists():
            import re
            event_re=re.compile(
                r"E62_BEMF_STRESS_DIAG vns=(\d+) a=(-?\d+) "
                r"b=(-?\d+) c=(-?\d+) d=(-?\d+) "
                r"e=(-?\d+) f=(\d+)")
            for row in qemu_diag.open(errors="replace"):
                m=event_re.search(row)
                if m:
                    analog_stress_count+=1
                    if int(m.group(6))!=0:
                        switch_noise_events+=1
        stress_source_proven=(
            a.bemf_robustness is None or
            (analog_stress_count>=1 and
             (not spike or switch_noise_events>=1)))
        # The immutable ORIGINAL SHA gate MUST reject candidate; if it
        # doesn't, fail closed because it means the strict gate was waived.
        original_guard_held="ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN" in failures
        result={
            "case":case,
            "bemf_robustness":a.bemf_robustness,
            "bemf_stress_source_events":analog_stress_count,
            "bemf_switching_artifact_events":switch_noise_events,
            "bemf_stress_source_proven":stress_source_proven,
            "status":"EXPERIMENTAL_DIAGNOSTIC_ONLY_NOT_P1",
            "candidate_sha256":candidate_sha,
            "source_scenario_sha256":sha256(scenario),
            "probe_exit_code":probe_rc,
            "unchanged_original_analyzer_exit_code":qual_rc,
            "strict_original_p1_qualified":False,
            "strict_original_p1_sha_guard_held":original_guard_held,
            "strict_original_p1_failures":failures,
            "scenario_physical_source_observed":(probe_rc==0 and report is not None),
            "direction_changes_observed":(
                (report or {}).get("significant_rotor_direction_changes")),
            "active_speed_signs_above_50rpm":(
                (report or {}).get("active_speed_signs_above_50rpm")),
            "source_guest_closed_loop_pwm_pairs":(
                (report or {}).get("source_guest_closed_loop_pwm_pairs")),
            "source_guest_cap1_w1c_ack":(
                (report or {}).get("source_guest_cap1_w1c_ack")),
            "source_guest_timg12_w1c_ack":(
                (report or {}).get("source_guest_timg12_w1c_ack")),
            "peak_abs_rpm":(report or {}).get("peak_abs_rpm_in_positive_window"),
            "artifacts":{"evidence":str(evidence),"events":str(events),
                         "strict_original_verdict":str(strict)},
        }
        result["non_sha_failures"]=[
            x for x in failures if x!="ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN"]
        result["diagnostic_mechanical_closed_loop_criteria_met"]=bool(
            probe_rc==0 and report is not None and original_guard_held and
            stress_source_proven and
            not result["non_sha_failures"] and
            result["direction_changes_observed"]==0 and
            result["active_speed_signs_above_50rpm"]==[1] and
            (result["source_guest_closed_loop_pwm_pairs"] or 0)>=12 and
            (result["source_guest_cap1_w1c_ack"] or 0)>=12 and
            (result["source_guest_timg12_w1c_ack"] or 0)>=12)
        results.append(result)
        print("E62_EXP_CANDIDATE_MATRIX_CASE "+json.dumps(result,sort_keys=True),flush=True)
    summary={
        "classification":"EXPERIMENT_DIAGNOSTICS_NOT_ORIGINAL_P1",
        "original_sha256":original_sha,
        "candidate_sha256":candidate_sha,
        "no_original_guest_gate_waiver":True,
        "formal_p0_p1_qualification":False,
        "physical_hardware_qualification":False,
        "cases":results,
    }
    dest=a.output/"e62-exp-candidate-matrix-summary.json"
    dest.write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
    print("E62_EXP_CANDIDATE_MATRIX_SUMMARY "+json.dumps({
        "summary":str(dest),
        "results":[[x["case"],x["diagnostic_mechanical_closed_loop_criteria_met"],
                    x["non_sha_failures"]] for x in results]
    },sort_keys=True),flush=True)
    # An experimental job is green only if EVERY unchanged non-SHA P1
    # physical/observability criterion passes AND the immutable Original
    # Guest SHA guard still rejects the non-original candidate.
    # This verdict is expressly NOT original P1 qualification.
    return 0 if all(x["diagnostic_mechanical_closed_loop_criteria_met"]
                    and x["strict_original_p1_sha_guard_held"]
                    and not x["strict_original_p1_qualified"]
                    for x in results) else 1


if __name__=="__main__":
    raise SystemExit(main())
