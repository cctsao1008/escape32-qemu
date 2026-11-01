#!/usr/bin/env python3
"""Issue #5 native timeout output audit: preserve ECAP PASS vs PWM safety.
Read only actual native probe artifact. Fail closed on missing provenance.
This tool deliberately does NOT assume that stop-on-timeout is original
Rel17 recovery policy: the verdict is a separate output-state diagnostic.
"""
import argparse
import json
from pathlib import Path


def verdict(artifact):
    failures = []
    report = artifact.get("g13b3i_original_no_bemf_timeout")
    if not isinstance(report, dict):
        return {"timeout_observed": False, "safe_off_observed": False,
                "failures": ["NATIVE_TIMEOUT_EVIDENCE_MISSING"]}
    before, after = report.get("pwm_before_timeout"), report.get("pwm_at_timeout")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {"timeout_observed": False, "safe_off_observed": False,
                "failures": ["NATIVE_PWM_SNAPSHOTS_MISSING"]}
    if report.get("simulator_feedback_injected") is not False:
        failures.append("FEEDBACK_PROVENANCE_INVALID")
    if before.get("native_pwm_valid") is not True or after.get("native_pwm_valid") is not True:
        failures.append("NATIVE_PWM_OBSERVER_INVALID")
    if (before.get("gate_and_pads") is not True or
        before.get("nonzero_phase_voltage_command") is not True):
        failures.append("PRE_TIMEOUT_POWERED_DRIVE_NOT_PROVEN")
    if after.get("gate_and_pads") is not False:
        failures.append("GATE_OR_PAD_STILL_CONNECTED_AT_TIMEOUT")
    if after.get("nonzero_phase_voltage_command") is not False:
        failures.append("ENERGIZED_PWM_IMAGE_RETAINED_AT_TIMEOUT")
    # Repeated post-timeout native WFI observations are independent of
    # the one-shot snapshot.  Never promote a single quiet instant to a
    # sustained bridge-safe claim.
    post = report.get("post_timeout_wfi_samples")
    if not isinstance(post, list) or len(post) < 48:
        failures.append("POST_TIMEOUT_HISTORY_INCOMPLETE")
    else:
        ticks = []
        for row in post:
            if isinstance(row, dict) and type(row.get("ecap_ticks")) is int:
                ticks.append(row["ecap_ticks"])
            else:
                failures.append("POST_TIMEOUT_NATIVE_TIMESTAMPS_MISSING")
                break
        # The source ECAP runs at 200 MHz; a list of 48 WFI samples alone
        # is not evidence of elapsed time. Require a measured 1ms horizon.
        if len(ticks) == len(post):
            diffs = [(ticks[i] - ticks[i-1]) & 0xffffffff
                     for i in range(1, len(ticks))]
            if any(delta == 0 or delta >= 0x80000000 for delta in diffs):
                failures.append("POST_TIMEOUT_TIMESTAMPS_INVALID")
            if ((ticks[-1] - ticks[0]) & 0xffffffff) < 200000:
                failures.append("POST_TIMEOUT_DURATION_UNPROVEN")
        for row in post:
            if not isinstance(row, dict) or not isinstance(row.get("pwm"), dict):
                failures.append("POST_TIMEOUT_SAMPLE_INVALID")
                break
            pwm = row["pwm"]
            if pwm.get("native_pwm_valid") is not True:
                failures.append("POST_TIMEOUT_PWM_OBSERVER_INVALID")
            if pwm.get("gate_and_pads") is not False:
                failures.append("POST_TIMEOUT_GATE_OR_PAD_CONNECTED")
            if pwm.get("nonzero_phase_voltage_command") is not False:
                failures.append("POST_TIMEOUT_ENERGIZED_PWM_RETAINED")
        if report.get("post_timeout_all_samples_six_off") is not True:
            failures.append("POST_TIMEOUT_ALL_SIX_OFF_NOT_PROVEN")
    return {
        "timeout_observed": bool(report.get("original_wfi_visits")) and\n                            report.get("simulator_feedback_injected") is False,
        "safe_off_observed": not failures,
        "failures": failures,
        "scope": "48_WFI_SNAPSHOTS_AT_LEAST_1MS_NOT_CONTINUOUS_TIME_PROOF",
        "firmware_fix_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--require-safe-off", action="store_true",
                        help="Separate exploratory strict output gate; not Rel17 compatibility claim")
    args = parser.parse_args()
    try:
        result = verdict(json.loads(args.artifact.read_text()))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["timeout_observed"]:
        raise SystemExit(1)
    if args.require_safe_off and not result["safe_off_observed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
