#!/usr/bin/env python3
"""Read-only, SIM_ONLY mechanical trajectory diagnostic for native E62 CI.

The source of samples is the independent host 24V open-star motor plant,
not an encoder or real E62 board. This module never sends Guest signals.
A genuine firmware-backed 12-sector result does not by itself establish
mechanical direction continuity or hardware stability.
"""
from dataclasses import dataclass, field
import math


@dataclass
class NativeRotorMotionAudit:
    # Diagnostic sensitivity only, NOT a physical acceptance requirement.
    # Reject tiny near-zero numerical chatter as a direction reversal.
    significant_rpm: float = 10.0
    post_six_samples: int = 0
    sign_changes: int = 0
    first_sign: int = 0
    last_sign: int = 0
    min_rpm: float = math.inf
    max_rpm: float = -math.inf
    max_abs_current_a: float = 0.0
    max_abs_dc_power_w: float = 0.0
    last_native_ns: int = 0
    first_sign_visit: int = 0
    reversals: list = field(default_factory=list)

    def observe(self, *, wfi_visit, completed_sectors, integrated_ns,
                rpm, phase_currents_a, dc_power_w):
        if not isinstance(wfi_visit, int) or wfi_visit < 1:
            raise ValueError("Original native WFI number required")
        if (not isinstance(integrated_ns, int) or integrated_ns < self.last_native_ns
                or completed_sectors < 0):
            raise ValueError("Real native integrated time/sectors invalid")
        if (len(phase_currents_a) != 3 or
                not all(math.isfinite(v) for v in
                        (rpm, dc_power_w, *phase_currents_a))):
            raise ValueError("Non-finite three-phase rotor/current/power model")
        if not math.isfinite(self.significant_rpm) or self.significant_rpm <= 0:
            raise ValueError("SIM_ONLY direction sensitivity invalid")
        self.min_rpm = min(self.min_rpm, rpm)
        self.max_rpm = max(self.max_rpm, rpm)
        self.max_abs_current_a = max(
            self.max_abs_current_a, *(abs(x) for x in phase_currents_a))
        self.max_abs_dc_power_w = max(self.max_abs_dc_power_w, abs(dc_power_w))
        self.last_native_ns = integrated_ns
        # Require the first complete native six-step cycle before testing
        # the direction of subsequent motion. Startup transients are
        # retained as extrema but do not bias the endurance sign result.
        if completed_sectors < 6:
            return
        self.post_six_samples += 1
        sign = (1 if rpm >= self.significant_rpm else
                -1 if rpm <= -self.significant_rpm else 0)
        if not sign:
            return
        if not self.first_sign:
            self.first_sign = sign
            self.first_sign_visit = wfi_visit
        if self.last_sign and sign != self.last_sign:
            self.sign_changes += 1
            if len(self.reversals) < 8:
                self.reversals.append({
                    "native_wfi_visit": wfi_visit,
                    "native_integrated_ns": integrated_ns,
                    "measured_sim_only_rpm": rpm,
                    "previous_sign": self.last_sign,
                    "new_sign": sign,
                    "completed_native_feedback_sectors": completed_sectors,
                })
        self.last_sign = sign

    def result(self):
        observed = self.post_six_samples > 0 and self.first_sign != 0
        return {
            "scope": "SIM_ONLY_UNCALIBRATED_OPEN_STAR_MODEL",
            "direction_sensitivity_rpm": self.significant_rpm,
            "post_six_sector_wfi_samples": self.post_six_samples,
            "initial_sign": self.first_sign,
            "first_sign_wfi_visit": self.first_sign_visit,
            "significant_direction_reversals": self.sign_changes,
            "reversal_examples": self.reversals,
            "min_simulated_rpm": (
                self.min_rpm if math.isfinite(self.min_rpm) else None),
            "max_simulated_rpm": (
                self.max_rpm if math.isfinite(self.max_rpm) else None),
            "peak_abs_model_phase_current_a": self.max_abs_current_a,
            "peak_abs_model_dc_power_w": self.max_abs_dc_power_w,
            "last_native_integrated_ns": self.last_native_ns,
            "direction_continuity_qualified_sim_only": (
                observed and self.sign_changes == 0),
            "physical_motor_stability_qualified": False,
        }
