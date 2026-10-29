#!/usr/bin/env python3
"""Fail-closed A/B verdict for source-built experimental BEMF CMPSS filtering.

Original strict P1 guest-SHA gate is IMMUTABLE and MUST reject both source
builds. The control is explicitly a negative control, NOT a P1 PASS.
"""
import argparse
import hashlib
import json
from pathlib import Path

ORIGINAL = "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
SHA_FAILURE = "ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN"
MOTOR_FAILURE = "STARTUP_SIGNIFICANT_DIRECTION_REVERSAL"

def sha256(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def load_case(root, profile, variant, stress):
    prefix=root / (profile + "-" + variant + "-" + stress)
    evidence=json.loads(prefix.with_suffix(".json").read_text())
    strict=json.loads(Path(str(prefix)+".strict-original-p1.json").read_text())
    qlog=prefix.with_suffix(".qemu.log").read_text(errors="replace")
    failures=strict.get("unwaived_observability_failures")
    if not isinstance(failures,list) or SHA_FAILURE not in failures:
        raise ValueError("ORIGINAL SHA gate not held for "+str(prefix))
    for key in ("host_guest_register_writes","used_guest_wfi_or_gdb",
                "synthetic_timed_bemf_enabled"):
        if evidence.get(key) is not False:
            raise ValueError("Host/source provenance not clean: "+key)
    if evidence.get("experimental_candidate_not_original") is not True:
        raise ValueError("Source built must NOT be classified as Original")
    if not evidence.get("readable_original_guest_diagnostics"):
        raise ValueError("No actual original Guest source diagnostic")
    diagnostic_events=sum(1 for line in qlog.splitlines()
        if "E62_BEMF_STRESS_DIAG " in line)
    if stress=="noise" and diagnostic_events==0:
        raise ValueError("Noise stress source not observed")
    if stress=="nominal" and diagnostic_events:
        raise ValueError("Noise source leaked into default-off baseline")
    counts={
        "pwm_pairs":strict.get("source_guest_closed_loop_pwm_pairs",0),
        "cap1_ack":strict.get("source_guest_cap1_w1c_ack",0),
        "timg12_ack":strict.get("source_guest_timg12_w1c_ack",0),
    }
    mechanical=(
        failures==[SHA_FAILURE] and
        strict.get("active_speed_signs_above_50rpm")==[1] and
        strict.get("significant_rotor_direction_changes")==0 and
        all(isinstance(v,int) and v>=12 for v in counts.values()))
    return {
        "label":str(prefix),"sha256":evidence["original_elf_sha256"],
        "failures":failures,"motor_reversals":strict.get("significant_rotor_direction_changes"),
        "speed_signs":strict.get("active_speed_signs_above_50rpm"),
        "counts":counts,"analog_source_events":diagnostic_events,
        "non_sha_closed_loop_pass":mechanical,
        "original_p1_qualified":False,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--dir",type=Path,required=True)
    p.add_argument("--profile",choices=["direct20","gentle"],required=True)
    p.add_argument("--source-commit",required=True)
    p.add_argument("--control-elf",type=Path,required=True)
    p.add_argument("--filter-elf",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if len(a.source_commit)!=40 or not all(c in "0123456789abcdef" for c in a.source_commit):
        p.error("Source commit requires exact 40-hex identity")
    control_sha,filtered_sha=sha256(a.control_elf),sha256(a.filter_elf)
    if len({ORIGINAL,control_sha,filtered_sha})!=3:
        p.error("Source A/B ELF identities must be distinct, not Original")
    data={f"{variant}_{stress}":load_case(a.dir,a.profile,variant,stress)
        for variant in ("control","filtered") for stress in ("nominal","noise")}
    for variant in ("control","filtered"):
        for stress in ("nominal","noise"):
            item=data[f"{variant}_{stress}"]
            if item["sha256"]!={"control":control_sha,"filtered":filtered_sha}[variant]:
                raise ValueError("ELF hash / probe SHA mismatch")
    # Nominal both variants must keep all UNCHANGED strict non-SHA gates.
    # Noise filtered must pass them too. Control noise is an intentionally
    # unwaived negative control; its actual result is retained.
    required=["control_nominal","filtered_nominal","filtered_noise"]
    problems=[name for name in required if not data[name]["non_sha_closed_loop_pass"]]
    cf=data["control_noise"];flt=data["filtered_noise"]
    if cf["motor_reversals"] is None or flt["motor_reversals"] is None:
        problems.append("MISSING_DIRECTION_COUNT")
    elif cf["motor_reversals"]>0:
        if flt["motor_reversals"]>=cf["motor_reversals"]:
            problems.append("NO_QUANTIFIED_NOISE_IMPROVEMENT")
    elif flt["motor_reversals"]!=0:
        problems.append("NOISE_REGRESSION_FROM_ZERO_BASELINE")
    # Direct20 already passed 0:16 in the pinned-ELF experiment.
    # A zero-reversal control CANNOT show a reduction below zero.
    # Require strict no-regression and preserve its distinct classification.
    can_claim_improvement=cf["motor_reversals"] is not None and cf["motor_reversals"]>0
    result={"schema":"e62.experimental.source-filter-ab.v1",
        "status":("FAIL_EXPERIMENT" if problems else
                  "PASS_EXPERIMENTAL_IMPROVEMENT" if can_claim_improvement else
                  "PASS_EXPERIMENTAL_NONREGRESSION"),
        "source_commit":a.source_commit,
        "profile":a.profile,
        "original_p1_qualified":False,
        "hardware_qualified":False,
        "source_control_sha256":control_sha,
        "source_filtered_sha256":filtered_sha,
        "strict_gate_unchanged":True,
        "violations":problems,
        "cases":data}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("E62_EXPERIMENTAL_BEMF_FILTER_A_B "+json.dumps(result,sort_keys=True))
    return 1 if problems else 0
if __name__=="__main__":
    raise SystemExit(main())
