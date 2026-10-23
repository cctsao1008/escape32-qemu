#!/usr/bin/env python3
"""Read-only closure/provenance check of new native SIM_ONLY energy ledgers.

A passing ACCOUNTING check proves the math in the reported host ledger
is self-consistent; it NEVER proves actual physical conservation,
numerical convergence, motor stability or independent strict acceptance.
"""
import argparse
import json
import math
from pathlib import Path


def check_energy_evidence(trace):
    if trace.get("format") != "e62.sitl.native-wfi.v1" or trace.get(
            "scope") != "SIM_ONLY_UNCALIBRATED_OPEN_STAR_MODEL":
        raise ValueError("Expected original native SIM_ONLY WFI trace")
    samples = trace.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("No actual original Guest WFI samples")
    result = trace.get("native_result")
    if not isinstance(result, dict):
        raise ValueError("Partial or old trace has no native failure/energy result")
    e = result.get("sim_only_energy_balance")
    if not isinstance(e, dict) or e.get("scope") != (
            "SIM_ONLY_SAMPLED_HOLD_NUMERICAL_ENERGY_DIAGNOSTIC"):
        raise ValueError("No new per-integration SIM_ONLY motor energy ledger")
    fields = (
        "model_bus_input_energy_j",
        "winding_copper_loss_energy_j",
        "viscous_friction_loss_energy_j",
        "load_loss_energy_j",
        "mechanical_kinetic_energy_change_j",
        "winding_magnetic_energy_change_j",
        "topology_projection_impulse_energy_j",
        "raw_energy_balance_residual_j",
        "integration_residual_excluding_topology_impulses_j",
        "topology_projection_absolute_energy_j",
    )
    if not all(isinstance(e.get(k), (int, float)) and
               math.isfinite(e[k]) for k in fields):
        raise ValueError("Nonfinite/missing model energy ledger entries")
    rhs = (e["model_bus_input_energy_j"] -
           e["winding_copper_loss_energy_j"] -
           e["viscous_friction_loss_energy_j"] -
           e["load_loss_energy_j"] -
           e["mechanical_kinetic_energy_change_j"] -
           e["winding_magnetic_energy_change_j"])
    integration = rhs + e["topology_projection_impulse_energy_j"]
    tolerance = 1e-9 * max(1.0, sum(abs(e[k]) for k in fields))
    if abs(e["raw_energy_balance_residual_j"] - rhs) > tolerance or (
            abs(e["integration_residual_excluding_topology_impulses_j"] -
                integration) > tolerance):
        raise ValueError("Corrupted/inconsistent per-integration energy accounting")
    if e.get("numerical_energy_balance_qualified") is not False or (
            e.get("commutation_current_continuity_qualified") is not False):
        raise ValueError("Model audit must NEVER imply resolved physical dynamics")
    # The native timeline intentionally SKIPS unresolved PWM-image change
    # intervals. A failed WFI can integrate one extra interval before the
    # analog frontend rejects it and no complete WFI is published.
    ceiling = len(samples) + (1 if trace.get(
        "capture_state") == "PARTIAL_EXCEPTION" else 0)
    if not isinstance(e.get("integration_intervals"), int) or (
            not 0 < e["integration_intervals"] <= ceiling):
        raise ValueError("Model energy-step count exceeds qualified WFI bounds")
    prior_intervals = 0
    for s in samples:
        snapshot = s.get("sim_only_energy_balance")
        if snapshot is None:
            raise ValueError("Missing energy snapshot from original Guest WFI")
        step_count = snapshot.get("integration_intervals")
        if not isinstance(step_count, int) or step_count < prior_intervals or (
                step_count > e["integration_intervals"]):
            raise ValueError("Invalid/rewound per-WFI energy integration count")
        prior_intervals = step_count
    if trace.get("capture_state") == "PARTIAL_EXCEPTION":
        failure = result.get("sim_only_failure_diagnostics")
        if not isinstance(failure, dict):
            raise ValueError("Fail-closed trace missing structured failure diagnostics")
        failed = result.get("failed_native_wfi_visit")
        last = result.get("last_complete_analog_injected_wfi")
        if not isinstance(failed, int) or not isinstance(last, int) or (
                failed <= last or last != len(samples)):
            raise ValueError("Invalid failure-boundary WFI evidence")
    return {
        "scope": "SIM_ONLY_ENERGY_LEDGER_ARITHMETIC_AND_FAILURE_EVIDENCE_ONLY",
        "native_wfi_samples": len(samples),
        "capture_state": trace["capture_state"],
        "integration_intervals": e["integration_intervals"],
        "input_energy_j": e["model_bus_input_energy_j"],
        "copper_loss_j": e["winding_copper_loss_energy_j"],
        "viscous_loss_j": e["viscous_friction_loss_energy_j"],
        "load_loss_j": e["load_loss_energy_j"],
        "kinetic_change_j": e["mechanical_kinetic_energy_change_j"],
        "magnetic_change_j": e["winding_magnetic_energy_change_j"],
        "topology_impulse_signed_j": e["topology_projection_impulse_energy_j"],
        "topology_impulse_abs_j": e["topology_projection_absolute_energy_j"],
        "raw_energy_balance_residual_j": e["raw_energy_balance_residual_j"],
        "integration_residual_excluding_topology_impulses_j":
            e["integration_residual_excluding_topology_impulses_j"],
        "original_cap1_accepted": sum(x.get("kind") == "CAP1_ACCEPTED"
                                     for x in trace.get("events", [])),
        "original_timg12_serviced": sum(x.get("kind") == "TIMG12_SERVICED"
                                       for x in trace.get("events", [])),
        "original_early_rejections": result.get("original_early_rejections"),
        "significant_direction_reversals":
            result.get("significant_direction_reversals"),
        "failure_diagnostics": result.get("sim_only_failure_diagnostics"),
        "audit_arithmetic_consistent": True,
        "numerical_energy_balance_qualified": False,
        "physical_motor_qualified": False,
        "strict_rotor_gate_executed_here": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--trace", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = check_energy_evidence(json.loads(args.trace.read_text()))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("E62_SIM_ONLY_NUMERICAL_ENERGY_AND_FAILURE_EVIDENCE " +
          json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
