#!/usr/bin/env python3
"""Read-only native SIM_ONLY plant/analog exception evidence.

Only computes host-side values from an already-observed motor sample.
Never reads/writes Guest SRAM, clears IRQs, clips analog values, or
modifies the original analog saturation exception policy.
"""
import math


def model_failure_evidence(exc, *, frontend, sample):
    reason = ("ANALOG_FRONTEND_SATURATION" if
              isinstance(exc, ValueError) and
              "BEMF analog fixture saturated" in str(exc) else
              "NATIVE_ECAP_TIMEBASE_STALLED" if
              "delta_ticks=0" in str(exc) else
              "SIM_ONLY_MOTOR_OR_ANALOG_EXCEPTION")
    limit_low = -frontend.zero_bemf_bias_v / frontend.input_gain_v_per_bemf_v
    limit_high = ((frontend.reference_v-frontend.zero_bemf_bias_v) /
                  frontend.input_gain_v_per_bemf_v)
    details = {
        "classification": reason,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "scope": "SIM_ONLY_UNCALIBRATED_ANALOG_FIXTURE",
        "reference_v": frontend.reference_v,
        "zero_bemf_bias_v": frontend.zero_bemf_bias_v,
        "input_gain_v_per_bemf_v": frontend.input_gain_v_per_bemf_v,
        "allowable_model_bemf_v": [limit_low, limit_high],
        "clipped_or_bypassed": False,
        "native_guest_writes": False,
        "failing_sample": None,
    }
    if sample is not None:
        measured = (sample.mechanical_rpm, sample.electrical_rad,
                    sample.electromagnetic_torque_nm,
                    *sample.phase_currents_a, *sample.bemf_phase_v)
        if all(isinstance(x, (float, int)) and math.isfinite(x)
               for x in measured):
            fixture_v = [
                frontend.zero_bemf_bias_v +
                frontend.input_gain_v_per_bemf_v * b
                for b in sample.bemf_phase_v]
            details["failing_sample"] = {
                "simulated_rpm": sample.mechanical_rpm,
                "electrical_rad": sample.electrical_rad,
                "phase_currents_a": list(sample.phase_currents_a),
                "bemf_phase_v": list(sample.bemf_phase_v),
                "analog_fixture_v_before_adc": fixture_v,
                "overrange_phases": [
                    "UVW"[i] for i,v in enumerate(fixture_v)
                    if not 0 <= v <= frontend.reference_v],
                "torque_nm": sample.electromagnetic_torque_nm,
            }
        else:
            details["failing_sample"] = "NONFINITE_MOTOR_STATE"
    return details
