#!/usr/bin/env python3
"""Deterministic, read-only frozen original-Guest PWM replay for E62 G13B3M.

Replays ONLY previously observed native-WFI qualified motor-integration
intervals using the pinned host VirtualBLDC. No QEMU/Guest invocation,
BEMF injection, firmware modification, analog gain change, physical
calibration, or independent strict rotor gate.

At a PWM transition the original native runtime deliberately skips the
unresolved interval. Replaying that interval as known is forbidden.
Substeps only subdivide intervals which the native timeline *did* integrate.
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.native_motor_model_profiles import (
    native_motor_parameters, native_motor_model_metadata)
from tools.native_power_coupled_plant import NativePowerCoupledBLDC
from tools.sitl_trace import FORMAT, SCOPE


def _angle_difference(a, b):
    return (a-b+math.pi) % (2*math.pi) - math.pi


def _check_trace(data):
    if data.get("format") != FORMAT or data.get("scope") != SCOPE:
        raise ValueError("Requires original SIM_ONLY native-WFI trace format")
    meta = data.get("metadata")
    if not isinstance(meta, dict) or meta.get(
            "host_guest_register_writes") is not False:
        raise ValueError("Frozen PWM replay needs no-Guest-writes provenance")
    profile = (meta.get("motor_model") or {}).get("profile")
    if profile not in ("legacy", "reciprocal"):
        raise ValueError("Embedded pinned motor-model profile required")
    expected = native_motor_model_metadata(profile)
    for k in ("profile", "ke_reference",
              "bemf_constant_v_per_electrical_rad_s",
              "torque_constant_nm_per_a", "pole_pairs"):
        if meta["motor_model"].get(k) != expected[k]:
            raise ValueError("Motor model provenance does not match pinned profile")
    angle = meta.get("initial_electrical_degrees")
    if not isinstance(angle, (int, float)) or not math.isfinite(angle):
        raise ValueError("Finite original starting rotor pose required")
    samples = data.get("samples")
    if not isinstance(samples, list) or len(samples) < 4:
        raise ValueError("At least four observed original native WFI samples")
    last_t, last_integrated, last_duties = -1, 0, None
    integrated = 0
    transitions = 0
    for idx, s in enumerate(samples, 1):
        if s.get("wfi") != idx or not isinstance(s.get("t_ns"), int) or (
                s["t_ns"] <= last_t):
            raise ValueError("Nonconsecutive WFI or nonmonotonic original ECAP")
        t = s["t_ns"]
        end = s.get("integrated_ns")
        if not isinstance(end, int) or not last_integrated <= end <= t:
            raise ValueError("Invalid integrated-time chronology")
        high = s.get("pwm_high_ticks")
        period = s.get("pwm_period_ticks")
        duty = s.get("pwm_duties")
        if (not isinstance(period, int) or period <= 0 or
                not isinstance(high, list) or len(high) != 6 or
                not isinstance(duty, list) or len(duty) != 6 or
                any(not isinstance(x, int) or x < 0 or x > period
                    for x in high) or
                any(not isinstance(x, (float, int)) or
                    not math.isfinite(x) or abs(x - h/period) > 1e-12
                    for x, h in zip(duty, high))):
            raise ValueError("Unqualified six actual sampled PWM outputs")
        if (s.get("gate_qualified") is not True or s.get("ost2") or
                s.get("ost3")):
            raise ValueError("Guest Gate/Trip state not qualified")
        delta = end - last_integrated
        qualifier = s.get("sampling_qualifier")
        if delta:
            integrated += 1
            if qualifier != "SAMPLED_HOLD_INTERVAL":
                raise ValueError("Must not integrate unresolved PWM interval")
            if last_duties is not None and high != last_duties:
                raise ValueError("Integrated interval has changed PWM image")
        elif qualifier == "PWM_CHANGE_UNRESOLVED_INTERVAL":
            transitions += 1
            if last_duties is not None and high == last_duties:
                raise ValueError("Claimed PWM transition without output change")
        elif qualifier == "SAMPLED_HOLD_INTERVAL":
            raise ValueError("Zero-time non-transition accepted as integrated")
        elif qualifier != "NATIVE_START_SNAPSHOT":
            raise ValueError("Unknown original-WFI PWM transition semantics")
        last_t, last_integrated, last_duties = t, end, list(high)
    return meta, samples, profile, integrated, transitions


def _run_one(samples, initial_deg, profile, subdivisions):
    p = native_motor_parameters(profile)
    motor = NativePowerCoupledBLDC(
        p, initial_electrical_rad=math.radians(initial_deg))
    last_ns = 0
    errors = {"rpm": 0.0, "angle_rad": 0.0, "current_a": 0.0}
    sum_sq_rpm = 0.0
    worst_rpm_wfi = None
    trajectory = []
    for s in samples:
        delta_ns = s["integrated_ns"]-last_ns
        if delta_ns:
            dt = (delta_ns / 1e9) / subdivisions
            pwm = [x/s["pwm_period_ticks"] for x in s["pwm_high_ticks"]]
            for _ in range(subdivisions):
                motor.advance(pwm, dt, gate_enabled=True)
        state = motor.sample(gate_enabled=True)
        rpm_error = abs(state.mechanical_rpm-s["motor_rpm"])
        angle_error = abs(_angle_difference(
            state.electrical_rad, s["electrical_rad"]))
        current_error = max(abs(a-b) for a,b in zip(
            state.phase_currents_a, s["phase_currents_a"]))
        if rpm_error > errors["rpm"]:
            errors["rpm"] = rpm_error
            worst_rpm_wfi = s["wfi"]
        errors["angle_rad"] = max(errors["angle_rad"], angle_error)
        errors["current_a"] = max(errors["current_a"], current_error)
        sum_sq_rpm += rpm_error**2
        trajectory.append({
            "wfi": s["wfi"],
            "rpm": state.mechanical_rpm,
            "angle_rad": state.electrical_rad,
            "current_a": list(state.phase_currents_a),
            "integrated_ns": s["integrated_ns"],
        })
        last_ns = s["integrated_ns"]
    energy = motor.energy_balance()
    return {
        "substeps": subdivisions,
        "observed_wfi_count": len(samples),
        "integrated_intervals": energy["integration_intervals"] // subdivisions,
        "integration_substeps": energy["integration_intervals"],
        "max_abs_rpm_error_vs_native_trace": errors["rpm"],
        "max_abs_angle_error_rad_vs_native_trace": errors["angle_rad"],
        "max_abs_phase_current_error_a_vs_native_trace": errors["current_a"],
        "rms_rpm_error_vs_native_trace": math.sqrt(sum_sq_rpm/len(samples)),
        "worst_rpm_error_wfi": worst_rpm_wfi,
        "last_state": trajectory[-1],
        "energy": energy,
        "_trajectory": trajectory,
    }


def frozen_pwm_convergence(data, *, steps=(1,2,4,8)):
    meta, samples, profile, count, transitions = _check_trace(data)
    if not steps or 1 not in steps or any(
            not isinstance(n, int) or n < 1 or n > 64 for n in steps):
        raise ValueError("Comparison needs baseline 1 and bounded substeps")
    if len(set(steps)) != len(steps):
        raise ValueError("Duplicate integration substep")
    runs = [_run_one(samples, meta["initial_electrical_degrees"],
                     profile, n) for n in steps]
    for run in runs:
        if run["integrated_intervals"] != count:
            raise ValueError("Replay failed to preserve qualified time intervals")
    baseline = next(x for x in runs if x["substeps"] == 1)
    # Verify exact same model/source and input chronology BEFORE comparing
    # numerical resolutions. This intentionally fails closed if an old
    # trace is incompatible with the source-pinned current native plant.
    max_reference_error_rpm = 1e-5
    max_reference_error_i = 1e-7
    max_reference_error_angle = 1e-7
    baseline_ok = (baseline["max_abs_rpm_error_vs_native_trace"] <=
                   max_reference_error_rpm and
                   baseline["max_abs_phase_current_error_a_vs_native_trace"] <=
                   max_reference_error_i and
                   baseline["max_abs_angle_error_rad_vs_native_trace"] <=
                   max_reference_error_angle)
    # Compare neighboring resolution levels as well as each level versus
    # the originally recorded native trajectory. N->2N convergence cannot
    # be inferred from the N=8 versus N=1 comparison alone.
    neighboring_resolutions = []
    sorted_runs = sorted(runs, key=lambda r: r["substeps"])
    for lo, hi in zip(sorted_runs, sorted_runs[1:]):
        a, b = lo["_trajectory"], hi["_trajectory"]
        neighboring_resolutions.append({
            "from_substeps": lo["substeps"],
            "to_substeps": hi["substeps"],
            "max_abs_rpm_difference": max(
                abs(x["rpm"]-y["rpm"]) for x,y in zip(a,b)),
            "max_abs_angle_difference_rad": max(
                abs(_angle_difference(x["angle_rad"],y["angle_rad"]))
                for x,y in zip(a,b)),
            "max_abs_phase_current_difference_a": max(
                abs(i-j) for x,y in zip(a,b)
                for i,j in zip(x["current_a"],y["current_a"])),
            "final_state_rpm_difference": (
                b[-1]["rpm"]-a[-1]["rpm"]),
        })
    results = []
    base_trajectory = baseline["_trajectory"]
    for run in runs:
        trajectory = run.pop("_trajectory")
        worst = max(trajectory, key=lambda s: abs(
            s["rpm"] - base_trajectory[s["wfi"]-1]["rpm"]))
        run["max_abs_rpm_difference_vs_1_step"] = max(
            abs(a["rpm"]-b["rpm"]) for a,b in
            zip(trajectory, base_trajectory))
        run["max_abs_angle_difference_rad_vs_1_step"] = max(
            abs(_angle_difference(a["angle_rad"],b["angle_rad"]))
            for a,b in zip(trajectory,base_trajectory))
        run["max_abs_current_difference_a_vs_1_step"] = max(
            abs(i-j) for a,b in zip(trajectory,base_trajectory)
            for i,j in zip(a["current_a"],b["current_a"]))
        run["largest_1_step_rpm_difference_wfi"] = worst["wfi"]
        results.append(run)
    if not baseline_ok:
        raise ValueError(
            "N=1 frozen PWM replay fails native recorded-state match; "
            "refuse numerical convergence claim: " + json.dumps({
                "rpm_max": baseline["max_abs_rpm_error_vs_native_trace"],
                "current_max": baseline["max_abs_phase_current_error_a_vs_native_trace"],
                "angle_rad_max": baseline[
                    "max_abs_angle_error_rad_vs_native_trace"],
            }, sort_keys=True))
    return {
        "scope": "HOST_ONLY_SAME_GUEST_PWM_SAMPLED_HOLD_NUMERICAL_CONVERGENCE",
        "elf_sha256": meta["elf_sha256"],
        "model_profile": profile,
        "recorded_capture_state": data.get("capture_state"),
        "observed_guest_wfi_count": len(samples),
        "observed_qualified_integration_intervals": count,
        "observed_unresolved_pwm_changes": transitions,
        "last_observed_native_ecap_ns": samples[-1]["t_ns"],
        "last_observed_model_integrated_ns": samples[-1]["integrated_ns"],
        "input_guest_pwm_samples_frozen": True,
        "guest_execution_or_feedback_rerun": False,
        "model_ODE_parameters_unchanged": True,
        "original_analog_frontend_gain_unchanged": True,
        "unresolved_pwm_transition_times_integrated": False,
        "same_source_step1_replay_match": True,
        "results": results,
        "neighboring_resolution_differences": neighboring_resolutions,
        "numerical_convergence_qualified": False,
        "physical_motor_qualified": False,
        "independent_strict_gate_executed": False,
        "notes": [
            "Substeps only split original native-integrated intervals",
            "No actual PWM edge history between WFI observations",
            "No BEMF feedback recomputation or real firmware commutation",
            "Phase-current projection occurs at first integration of new bridge",
            "Partial native trace stops before failed WFI plant state",
            "Numerical convergence requires separate interpretation of n=2,4,8",
        ],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--trace", type=Path, required=True)
    p.add_argument("--substeps", type=int, nargs="+", default=(1,2,4,8))
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = frozen_pwm_convergence(
        json.loads(args.trace.read_text()), steps=tuple(args.substeps))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+"\n")
    print("E62_SIM_ONLY_FROZEN_PWM_CONVERGENCE " +
          json.dumps(result,sort_keys=True))


if __name__ == "__main__":
    main()
