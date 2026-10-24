#!/usr/bin/env python3
"""Host-only *synthetic* explicit-switch/current continuity benchmark.

The stage schedule is test-fixture H/L/Z edges; it is NOT reconstructed
from Native guest WFI PWM high-tick averages. No guest execution.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.current_continuous_bldc import CurrentContinuousBLDC, LegTopology
from tools.native_motor_model_profiles import native_motor_parameters


STAGES = (
    (("H", "L", "Z"), 200),
    (("Z", "H", "L"), 200),
    (("L", "H", "Z"), 200),
    (("Z", "Z", "Z"), 30),
)
BASE_DT_S = 1e-6


def benchmark(*, substeps=(1, 2, 4, 8)):
    if not substeps or len(set(substeps)) != len(substeps) or any(
            type(n) is not int or not 1 <= n <= 64 for n in substeps):
        raise ValueError("Distinct integer substeps 1..64 required")
    data = []
    for n in substeps:
        model = CurrentContinuousBLDC(
            native_motor_parameters("reciprocal"),
            initial_electrical_rad=0.2, diode_forward_v=0.7,
            max_electrical_step_rad=0.35)
        for switch, base_intervals in STAGES:
            model.set_switches(LegTopology(switch))
            for _ in range(base_intervals*n):
                model.advance(BASE_DT_S/n)
        d = model.diagnostics()
        if d["forced_current_projection_impulse_energy_j"] != 0:
            raise AssertionError("Unmodeled projection energy reintroduced")
        data.append({
            "substeps": n,
            "final_rpm": model.sample().mechanical_rpm,
            "final_angle_rad": model.sample().electrical_rad,
            "final_currents_a": list(model.iabc),
            "model_energy": d,
        })
    return {
        "scope": "HOST_ONLY_DECLARED_SYNTHETIC_SWITCHING_FIXTURE",
        "switching_schedule": [
            {"legs": list(states), "base_intervals": periods,
             "base_dt_s": BASE_DT_S} for states, periods in STAGES],
        "reciprocal_model": True,
        "actual_native_pwm_edges_supplied": False,
        "actual_native_wfi_replay": False,
        "non_silicon_ideal_diode_assumption": True,
        "forced_current_projection_qualified_absent": True,
        "numeric_timestep_convergence_qualified": False,
        "physical_motor_qualified": False,
        "native_strict_gate_executed": False,
        "results": data,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--substeps", nargs="+", type=int,
                   default=(1, 2, 4, 8))
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    result = benchmark(substeps=tuple(a.substeps))
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(result, indent=2)+"\n")
    print("E62_CURRENT_CONTINUOUS_HOST_SWITCH_BENCHMARK " +
          json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
