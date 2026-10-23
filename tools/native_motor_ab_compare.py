#!/usr/bin/env python3
"""Compare same-ELF native SIM_ONLY baseline/reciprocal trace evidence.

Observational comparison only. No retries, no Guest writes, no relaxation
of independent G13B3M strict rotor acceptance.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.native_energy_reciprocity_audit import audit_trace


def compare_traces(baseline, reciprocal, *, allow_old_baseline=False):
    left = audit_trace(baseline, "legacy", allow_missing_profile=allow_old_baseline)
    right = audit_trace(reciprocal, "reciprocal")
    a, b = baseline["metadata"], reciprocal["metadata"]
    required = ("elf_sha256", "initial_electrical_degrees",
                "required_sectors", "required_integrated_ns")
    diffs = {key: (a.get(key), b.get(key))
             for key in required if a.get(key) != b.get(key) or a.get(key) is None}
    if diffs:
        raise ValueError("A/B invalid: mismatched original ELF/input constraints: " +
                         repr(diffs))
    if a.get("host_guest_register_writes") is not False or (
            b.get("host_guest_register_writes") is not False):
        raise ValueError("A/B traces must prohibit Host Guest-register writes")

    def snapshot(trace, energy):
        samples = trace["samples"]
        events = trace.get("events", [])
        verdict = trace.get("native_result") or {}
        return {
            "motor_model": energy["profile"],
            "profile_provenance": energy["profile_provenance"],
            "observed_wfi_samples": len(samples),
            "ecap_elapsed_last_ms": samples[-1]["t_ns"] / 1e6,
            "plant_integrated_last_ms": samples[-1]["integrated_ns"] / 1e6,
            "accepted_cap1_events": sum(
                e.get("kind") == "CAP1_ACCEPTED" for e in events),
            "serviced_timg12_events": sum(
                e.get("kind") == "TIMG12_SERVICED" for e in events),
            "last_native_guest_step": samples[-1]["guest_step"],
            "last_native_guest_rejections": samples[-1]["guest_rejected"],
            "min_simulated_rpm": min(s["motor_rpm"] for s in samples),
            "max_simulated_rpm": max(s["motor_rpm"] for s in samples),
            "peak_abs_simulated_phase_current_a": max(
                abs(i) for s in samples for i in s["phase_currents_a"]),
            "significant_direction_reversals": verdict.get(
                "significant_direction_reversals"),
            "sim_only_direction_qualified": verdict.get(
                "direction_continuity_qualified_sim_only"),
            "capture_state": trace.get("capture_state"),
            "error_type": trace.get("error_type"),
            "native_trace_report_available": bool(verdict),
            "instantaneous_reciprocity_qualified_sim_only":
                energy["instantaneous_reciprocity_qualified_sim_only"],
        }
    return {
        "comparison_scope": "SAME_PINNED_ELF_SIM_ONLY_MODEL_AB_NOT_HARDWARE",
        "elf_sha256": a["elf_sha256"],
        "baseline": snapshot(baseline, left),
        "reciprocal": snapshot(reciprocal, right),
        "native_extended_gate_verdict": "NOT_EXECUTED_BY_COMPARATOR",
        "differing_guest_events_can_result_from_model_BEMF_FEEDBACK": True,
        "physical_stability_qualified": False,
        "numerical_integrator_energy_qualified": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--baseline-trace", required=True, type=Path)
    p.add_argument("--reciprocal-trace", required=True, type=Path)
    p.add_argument("--allow-pre-profile-legacy-baseline", action="store_true")
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = compare_traces(
        json.loads(args.baseline_trace.read_text()),
        json.loads(args.reciprocal_trace.read_text()),
        allow_old_baseline=args.allow_pre_profile_legacy_baseline)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("E62_SIM_ONLY_NATIVE_MODEL_AB_COMPARISON " +
          json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
