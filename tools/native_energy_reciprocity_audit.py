#!/usr/bin/env python3
"""Read-only E62 SIM_ONLY electromagnetic reciprocity audit on WFI traces.

Check P_em_electrical=sum(e_phase*i_phase) versus P_em_mechanical=Te*omega_mech.
This is an instantaneous identity only; not bus power balance, numerical
integrator convergence, semiconductor losses, or qualified motor operation.
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.native_motor_model_profiles import (
    PROFILES, native_motor_parameters, native_motor_model_metadata)


def audit_trace(data, profile, *, allow_missing_profile=False):
    if data.get("format") != "e62.sitl.native-wfi.v1" or (
            data.get("scope") != "SIM_ONLY_UNCALIBRATED_OPEN_STAR_MODEL"):
        raise ValueError("Not an original SIM_ONLY native-WFI trace")
    samples = data.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("No observed native-WFI sample evidence")
    p = native_motor_parameters(profile)
    expected = native_motor_model_metadata(profile)
    model = data.get("metadata", {}).get("motor_model")
    if model is None:
        if not allow_missing_profile:
            raise ValueError(
                "Pre-profile trace: explicitly opt in to source-pinned "
                "legacy assumption; model identity not embedded in trace")
        if profile != "legacy":
            raise ValueError("Missing embedded model metadata only allowed for legacy")
        provenance = "EXPLICIT_PRE_PROFILE_LEGACY_SOURCE_ASSUMPTION"
    else:
        for key in ("profile", "ke_reference",
                    "bemf_constant_v_per_electrical_rad_s",
                    "torque_constant_nm_per_a", "pole_pairs"):
            if model.get(key) != expected[key]:
                raise ValueError(f"Embedded motor-model mismatch at {key}")
        provenance = "TRACE_EMBEDDED_PROFILE"

    max_bemf_error_v = 0.0
    max_relative_power_error = 0.0
    max_abs_power_residual_w = 0.0
    powered_samples = 0
    previous_wfi = 0
    last_ecap_ns = -1
    for s in samples:
        wfi, t_ns = s["wfi"], s["t_ns"]
        if wfi <= previous_wfi or t_ns <= last_ecap_ns:
            raise ValueError("Nonmonotonic native WFI/ECAP trace")
        previous_wfi, last_ecap_ns = wfi, t_ns
        omega = s["motor_rpm"] * 2.0 * math.pi / 60.0
        theta = s["electrical_rad"]
        current = s["phase_currents_a"]
        bemf = s["bemf_phase_v"]
        if len(current) != 3 or len(bemf) != 3 or not all(
                math.isfinite(x) for x in
                (omega, theta, *current, *bemf)):
            raise ValueError("Invalid/nonfinite phase observation")
        basis = (math.sin(theta),
                 math.sin(theta - 2 * math.pi / 3),
                 math.sin(theta + 2 * math.pi / 3))
        expectation = [p.bemf_constant_v_per_rad_s *
                       p.pole_pairs * omega * b for b in basis]
        max_bemf_error_v = max(
            max_bemf_error_v,
            *(abs(e - x) for e, x in zip(bemf, expectation)))
        torque = p.torque_constant_nm_per_a * sum(
            i*b for i, b in zip(current, basis))
        pe = sum(i*e for i, e in zip(current, bemf))
        pm = torque * omega
        if max(abs(pe), abs(pm)) < 1e-6:
            continue
        powered_samples += 1
        max_abs_power_residual_w = max(
            max_abs_power_residual_w, abs(pe-pm))
        max_relative_power_error = max(
            max_relative_power_error,
            abs(pe - pm) / max(abs(pe), abs(pm), 1e-6))
    if powered_samples == 0:
        raise ValueError("No nontrivial electromagnetic power samples")
    # Trace BEMF and phase currents must match the pinned model equation.
    # This tests the reciprocity identity, not actual integration energy balance.
    if max_bemf_error_v > 1e-7:
        raise ValueError("Trace BEMF is not from the expected pinned model")

    qualified = (expected["electromagnetic_reciprocal"] and
                 max_relative_power_error < 1e-9)
    return {
        "scope": "SIM_ONLY_INSTANTANEOUS_ELECTROMAGNETIC_POWER_RECIPROCITY",
        "profile": profile,
        "profile_provenance": provenance,
        "elf_sha256": data.get("metadata", {}).get("elf_sha256"),
        "total_native_wfi_samples": len(samples),
        "nonzero_electromagnetic_power_samples": powered_samples,
        "max_bemf_equation_error_v": max_bemf_error_v,
        "max_instantaneous_power_error_w": max_abs_power_residual_w,
        "max_relative_power_error": max_relative_power_error,
        "theoretical_pe_over_pm_ratio": expected[
            "electromagnetic_power_ratio_pe_over_pm"],
        "instantaneous_reciprocity_qualified_sim_only": qualified,
        "numerical_energy_balance_qualified": False,
        "physical_motor_calibrated": False,
        "native_rotor_direction_qualified_by_this_audit": False,
    }


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument("--trace", type=Path, required=True)
    pa.add_argument("--profile", choices=PROFILES, required=True)
    pa.add_argument("--allow-pre-profile-legacy-trace", action="store_true")
    pa.add_argument("--output", type=Path)
    args = pa.parse_args()
    result = audit_trace(
        json.loads(args.trace.read_text()), args.profile,
        allow_missing_profile=args.allow_pre_profile_legacy_trace)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("E62_SIM_ONLY_EM_RECIPROCITY_AUDIT " +
          json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
