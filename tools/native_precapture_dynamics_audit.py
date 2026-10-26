#!/usr/bin/env python3
"""G20 read-only WFI pre-first-CAP1 motor dynamics; not a strict qualification.

Use only an original-Guest source-clocked current-continuous WFI trace.
Each current, angle and RPM is a stopped-Guest WFI snapshot, NOT an
event-atomic or substep-resolved torque measurement. No stimulus or
firmware/Guest/QEMU/motor-parameter writes are performed.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

OFFSETS = (0.0, -2.0 * math.pi / 3.0, 2.0 * math.pi / 3.0)
RPM_TO_RAD_S = 2.0 * math.pi / 60.0


def _finite_number(x, name):
    if type(x) not in (int, float) or not math.isfinite(x):
        raise ValueError("Invalid finite " + name)
    return float(x)


def _wfi_snapshot(sample, kt):
    current = sample.get("phase_currents_a")
    if type(current) not in (list, tuple) or len(current) != 3:
        raise ValueError("Missing native three-phase WFI currents")
    currents = [_finite_number(x, "current") for x in current]
    theta = _finite_number(sample.get("electrical_rad"), "electrical angle")
    rpm = _finite_number(sample.get("motor_rpm"), "RPM")
    high = sample.get("pwm_high_ticks")
    if type(high) not in (list, tuple) or len(high) != 6 or any(
            type(x) is not int or x < 0 for x in high):
        raise ValueError("Missing original Guest six-pad WFI PWM history")
    step = sample.get("guest_step")
    if type(step) is not int or not 1 <= step <= 6:
        raise ValueError("Missing original Guest six-step selection")
    code = sample.get("guest_selected_code")
    if type(code) is not int:
        raise ValueError("Missing original Guest comparator selection")
    torque = kt * sum(i * math.sin(theta + offset)
                      for i, offset in zip(currents, OFFSETS))
    if not math.isfinite(torque):
        raise ValueError("Nonfinite modeled electromagnetic torque")
    return {
        "wfi": sample["wfi"],
        "t_ns": sample["t_ns"],
        "rpm": rpm,
        "electrical_angle_deg": math.degrees(theta) % 360.0,
        "phase_currents_a": currents,
        "modeled_electromagnetic_torque_nm_at_wfi": torque,
        "guest_step": step,
        "guest_selected_code": code,
        "original_pwm_six_high_ticks": list(high),
        "gate_qualified_wfi": sample.get("gate_qualified"),
        "ost2_wfi": sample.get("ost2"),
        "ost3_wfi": sample.get("ost3"),
    }


def audit(document):
    meta = document.get("metadata") or {}
    motor = meta.get("motor_model") or {}
    if (document.get("format") != "e62.sitl.native-wfi.v1" or
            document.get("scope") != "SIM_ONLY_UNCALIBRATED_OPEN_STAR_MODEL" or
            meta.get("host_guest_register_writes") is not False or
            motor.get("electromagnetic_reciprocal") is not True or
            motor.get("physical_motor_calibrated") is not False):
        raise ValueError("Require unchanged original Guest source-clocked SIM_ONLY trace")
    kt = _finite_number(motor.get("torque_constant_nm_per_a"), "Kt")
    if kt <= 0:
        raise ValueError("Require strictly positive model Kt")
    samples = document.get("samples")
    events = document.get("events")
    if not isinstance(samples, list) or len(samples) < 3 or not isinstance(events, list):
        raise ValueError("Original native WFI and events required")
    cap1 = [x for x in events if x.get("kind") == "CAP1_ACCEPTED"]
    if not cap1 or any(type(x.get("t_ns")) is not int for x in cap1):
        raise ValueError("Original Guest accepted CAP1 timestamp required")
    first_cap1_ns = min(x["t_ns"] for x in cap1)
    if first_cap1_ns <= 0:
        raise ValueError("Original Guest CAP1 timestamp invalid")
    previous_ns = -1
    snapshots = []
    for index, s in enumerate(samples, 1):
        if (type(s) is not dict or s.get("wfi") != index or
                type(s.get("t_ns")) is not int or s["t_ns"] <= previous_ns or
                s.get("sampling_qualifier") !=
                "EXTERNAL_CLOCKED_CURRENT_CONTINUOUS_NO_AVERAGE"):
            raise ValueError("WFI chronology/clocked PWM provenance invalid")
        previous_ns = s["t_ns"]
        if s["t_ns"] < first_cap1_ns:
            snapshots.append(_wfi_snapshot(s, kt))
    if len(snapshots) < 3:
        raise ValueError("Insufficient pre-first-CAP1 original WFI evidence")

    flips = []
    decelerations = []
    for before, after in zip(snapshots, snapshots[1:]):
        interval = {
            "wfi_before": before["wfi"],
            "wfi_after": after["wfi"],
            "bracket_ns": [before["t_ns"], after["t_ns"]],
            "rpm_before": before["rpm"],
            "rpm_after": after["rpm"],
            "modeled_torque_before_nm": before[
                "modeled_electromagnetic_torque_nm_at_wfi"],
            "modeled_torque_after_nm": after[
                "modeled_electromagnetic_torque_nm_at_wfi"],
            "mean_observed_acceleration_rad_s2": (
                (after["rpm"] - before["rpm"]) * RPM_TO_RAD_S /
                ((after["t_ns"] - before["t_ns"]) * 1e-9)),
        }
        if before["rpm"] * after["rpm"] < 0:
            flips.append(interval)
        if after["rpm"] < before["rpm"]:
            decelerations.append(interval)
    negative_torque = [
        s for s in snapshots
        if s["modeled_electromagnetic_torque_nm_at_wfi"] < -1e-9
    ]
    positive_rpm_braking = [
        s for s in negative_torque if s["rpm"] > 0
    ]
    first_flip = flips[0] if flips else None
    first_flip_window = []
    if first_flip:
        idx = first_flip["wfi_before"] - 1
        first_flip_window = snapshots[max(0, idx-3):min(len(snapshots), idx+5)]
    return {
        "status": "DIAGNOSTIC_ONLY_PRE_FIRST_CAP1_NOT_STRICT_ROTOR_QUALIFICATION",
        "original_guest_elf_sha256": meta.get("elf_sha256"),
        "profile": motor.get("profile"),
        "first_original_cap1_ns": first_cap1_ns,
        "pre_first_cap1_wfi_count": len(snapshots),
        "observed_pre_cap1_speed_sign_change_count": len(flips),
        "first_pre_cap1_speed_sign_change": first_flip,
        "first_four_pre_cap1_speed_sign_changes": flips[:4],
        "first_pre_cap1_deceleration_interval": (
            decelerations[0] if decelerations else None),
        "first_pre_cap1_negative_torque_wfi": (
            negative_torque[0] if negative_torque else None),
        "first_pre_cap1_positive_rpm_negative_torque_wfi": (
            positive_rpm_braking[0] if positive_rpm_braking else None),
        "first_speed_sign_change_wfi_window": first_flip_window,
        "sampled_peak_abs_pre_cap1_current_a": max(
            abs(i) for s in snapshots for i in s["phase_currents_a"]),
        "sampled_min_pre_cap1_torque_nm": min(
            s["modeled_electromagnetic_torque_nm_at_wfi"] for s in snapshots),
        "model_torque_from_WFI_currents_and_sine_basis_only": True,
        "cap1_not_host_generated": True,
        "physical_motor_qualified": False,
        "guest_writes": False,
        "strict_gate_modified": False,
        "caveat": ("WFI instantaneous current/torque and average RPM change "
                   "cannot isolate substep PWM-edge torque or imply real "
                   "motor behavior; no physical parameter calibration."),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(json.loads(args.trace.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    brief_keys = (
        "status", "first_original_cap1_ns", "pre_first_cap1_wfi_count",
        "observed_pre_cap1_speed_sign_change_count",
        "first_pre_cap1_speed_sign_change",
        "first_pre_cap1_negative_torque_wfi",
        "first_pre_cap1_positive_rpm_negative_torque_wfi",
        "sampled_peak_abs_pre_cap1_current_a",
        "sampled_min_pre_cap1_torque_nm",
        "physical_motor_qualified", "guest_writes", "strict_gate_modified",
    )
    print("G20_PRE_CAP1_CLOCKED_MOTOR_DYNAMICS_DIAGNOSTIC " +
          json.dumps({k: result[k] for k in brief_keys}, sort_keys=True),
          flush=True)


if __name__ == "__main__":
    main()
