#!/usr/bin/env python3
"""Additional G13B3M fail-closed gate for *native* twelve-sector QEMU evidence.

Consumes original firmware-backed probe JSON. No Guest/QEMU write access.
Unit tests are synthetic and NEVER constitute a native firmware PASS.
The output is SIM_ONLY evidence, not board-current or thermal measurement.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_closed_loop_audit import ORIGINAL_REL17_ROUTE


class ExtendedRunError(AssertionError):
    pass


def check_native_extended_run(data, *, min_sectors=12,
                              min_integrated_ns=90_000_000,
                              min_powered_pwm_samples=600):
    """Require two source-ordered complete, feedback-powered six-step cycles."""
    if not isinstance(data, dict) or data.get("status") != "NATIVE_GATE_ON":
        raise ExtendedRunError("Original ELF native Gate-ON proof missing")
    loop = data.get("g13b3l_native_sustained_loop")
    if not isinstance(loop, dict) or loop.get("qualified") is not True:
        raise ExtendedRunError("Original firmware native sustained loop not qualified")
    if min_sectors < 12 or min_sectors % 6:
        raise ValueError("G13B3M requires a multiple of six sectors, at least twelve")
    if not isinstance(min_integrated_ns, int) or min_integrated_ns <= 0:
        raise ValueError("Native integrated minimum must be positive")
    if not isinstance(min_powered_pwm_samples, int) or min_powered_pwm_samples < min_sectors:
        raise ValueError("Powered sample minimum below complete sectors")
    sectors = loop.get("sector_evidence")
    if (not isinstance(sectors, list) or
            len(sectors) < min_sectors or
            loop.get("completed_feedback_powered_sectors") != len(sectors) or
            loop.get("required_sectors") < min_sectors):
        raise ExtendedRunError("Insufficient genuine native powered CAP1/TIMG12 sectors")
    if (loop.get("plant_integrated_ns", 0) < min_integrated_ns or
            loop.get("powered_pwm_samples", 0) < min_powered_pwm_samples or
            loop.get("simulator_analog_frames", 0) < min_powered_pwm_samples):
        raise ExtendedRunError("Native ECAP/WFI integrated duration or powered PWM sampling insufficient")
    if (loop.get("original_unpowered_timg12_steps", 0) != 0 or
            not loop.get("motor_started_only_after_cross_phase")):
        raise ExtendedRunError("Unpowered commutation or model-only motor startup")
    power = loop.get("native_effective_power")
    if (not isinstance(power, dict) or
            not power.get("gate_connected") or
            not power.get("original_ost2_clear") or
            not power.get("original_ost3_clear") or
            power.get("qualified_consecutive_wfi", 0) < 3 or
            power.get("simulated_net_dc_energy_j", 0) <= 0 or
            power.get("simulated_net_electromagnetic_work_j", 0) <= 0):
        raise ExtendedRunError("No independent qualified cross-phase model-energy gate")
    if loop.get("original_guest_wfi_visits", 0) < min_powered_pwm_samples:
        raise ExtendedRunError("Real original WFI observation count insufficient")

    preceding_capture = None
    preceding_service = None
    for i, sector in enumerate(sectors[:min_sectors]):
        before = (i % 6) + 1
        after = (before % 6) + 1
        if (sector.get("guest_step_before") != before or
                sector.get("guest_step_after") != after or
                sector.get("guest_selected_code_before") != ORIGINAL_REL17_ROUTE[before][0] or
                sector.get("guest_selected_code_after") != ORIGINAL_REL17_ROUTE[after][0] or
                tuple(sector.get("prior_source_return", ())) != ORIGINAL_REL17_ROUTE[before][1] or
                tuple(sector.get("next_source_return", ())) != ORIGINAL_REL17_ROUTE[after][1]):
            raise ExtendedRunError(f"Original Rel17 native commutation sequence incorrect at sector {i+1}")
        before_pwm = sector.get("pwm_before")
        after_pwm = sector.get("pwm_after")
        if (not isinstance(before_pwm, list) or
                not isinstance(after_pwm, list) or
                len(before_pwm) != 6 or len(after_pwm) != 6 or
                before_pwm == after_pwm or
                not any(v > 0 for v in before_pwm) or
                not any(v > 0 for v in after_pwm)):
            raise ExtendedRunError(f"Powered six-output PWM transition absent at sector {i+1}")
        capture = sector.get("accepted_cap1_ticks")
        service = sector.get("serviced_ecap_ticks")
        if not isinstance(capture, int) or not isinstance(service, int):
            raise ExtendedRunError("Original native ECAP capture/service timestamps missing")
        if not 0 < ((service - capture) & 0xffffffff) < 0x80000000:
            raise ExtendedRunError("Original TIMG12 service not after native CAP1")
        if preceding_capture is not None:
            if not 0 < ((capture - preceding_capture) & 0xffffffff) < 0x80000000:
                raise ExtendedRunError("Native CAP1 time not strictly monotonic")
            if not 0 < ((service - preceding_service) & 0xffffffff) < 0x80000000:
                raise ExtendedRunError("Native TIMG12 service time not strictly monotonic")
        preceding_capture, preceding_service = capture, service

    return {
        "qualified": True,
        "scope": "SIM_ONLY_ORIGINAL_ELF_NOT_PHYSICAL_HARDWARE",
        "consecutive_native_feedback_powered_sectors": min_sectors,
        "complete_source_ordered_cycles": min_sectors // 6,
        "actual_native_integrated_ns": loop["plant_integrated_ns"],
        "actual_native_wfi_visits": loop["original_guest_wfi_visits"],
        "actual_powered_pwm_samples": loop["powered_pwm_samples"],
        "simulated_positive_dc_energy_j": power["simulated_net_dc_energy_j"],
        "original_cpu_and_trip_qualification": "INHERITED_FROM_STRICT_G13B3L",
        "hardware_pwm_current_protection_thermal": "OPEN_NOT_MEASURED",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--artifact", required=True, type=Path)
    p.add_argument("--min-sectors", type=int, default=12)
    p.add_argument("--min-integrated-ns", type=int, default=90_000_000)
    p.add_argument("--min-powered-pwm-samples", type=int, default=600)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    data = json.loads(a.artifact.read_text())
    result = check_native_extended_run(
        data, min_sectors=a.min_sectors,
        min_integrated_ns=a.min_integrated_ns,
        min_powered_pwm_samples=a.min_powered_pwm_samples)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(result, indent=2) + "\n")
    print("PASS_G13B3M_EXTENDED_ORIGINAL_NATIVE_TWO_FULL_POWERED_CYCLES " +
          json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
