#!/usr/bin/env python3
"""G15 read-only SIM_ONLY rotor electrical phase vs ORIGINAL Rel17 sixstep.

Consumes only already-observed Guest WFI step/phase-current/model rotor pose.
Does not inject Guest signals, tune model physics, or waive any strict gate.
WFI snapshots are not atomic CAP1/TIMG12 commutation instants. Unwrapped
electrical angle assumes less than 180 degrees of motion between WFI visits.
"""
from __future__ import annotations

import math
from tools.native_closed_loop_audit import ORIGINAL_REL17_ROUTE

OFFSETS = (0.0, -2.0 * math.pi / 3.0, 2.0 * math.pi / 3.0)


def _shortest_deg(value):
    return (value + 180.0) % 360.0 - 180.0


def _source_field_target_deg(guest_step):
    """Rotor angle for peak positive source-minus-return torque."""
    source, sink = ORIGINAL_REL17_ROUTE[guest_step][1]
    a = math.cos(OFFSETS[source]) - math.cos(OFFSETS[sink])
    b = math.sin(OFFSETS[source]) - math.sin(OFFSETS[sink])
    return math.degrees(math.atan2(a, b)) % 360.0


class NativeRotorPhaseAudit:
    """Capture phase-slip causes, not accept/reject the motor trajectory."""

    def __init__(self, *, pole_pairs=7, significant_rpm=10.0):
        if type(pole_pairs) is not int or pole_pairs < 1:
            raise ValueError("Physical model pole-pair count required")
        if not math.isfinite(significant_rpm) or significant_rpm <= 0:
            raise ValueError("Finite significant RPM sensitivity required")
        self.pole_pairs = pole_pairs
        self.significant_rpm = float(significant_rpm)
        self.last_visit = 0
        self.last_time_ns = -1
        self.last_wrapped_deg = None
        self.unwrapped_deg = None
        self.origin_deg = None
        self.last_sectors = 0
        self.last_sector_rotor_deg = None
        self.last_sign = 0
        self.post_six_samples = 0
        self.negative_torque_samples = 0
        self.reverse_rpm_samples = 0
        self.field_error_gt_90_samples = 0
        self.source_pair_mismatch_samples = 0
        self.max_abs_slip_deg = 0.0
        self.first_direction_reversal = None
        self.sector_checkpoints = []
        self.reversal_checkpoints = []
        self.last_snapshot = None

    def observe(self, *, wfi_visit, integrated_ns, completed_sectors,
                guest_step, electrical_rad, mechanical_rpm,
                phase_currents_a, torque_constant_nm_per_a, observed_pair):
        if (type(wfi_visit) is not int or wfi_visit != self.last_visit + 1 or
                type(integrated_ns) is not int or integrated_ns < self.last_time_ns or
                type(completed_sectors) is not int or
                completed_sectors < self.last_sectors or
                completed_sectors > self.last_sectors + 1 or
                type(guest_step) is not int or not 1 <= guest_step <= 6):
            raise ValueError("Nonconsecutive original WFI/sector/step provenance")
        if (len(phase_currents_a) != 3 or
                not all(isinstance(v, (int, float)) and math.isfinite(v)
                        for v in (*phase_currents_a, electrical_rad,
                                  mechanical_rpm, torque_constant_nm_per_a)) or
                torque_constant_nm_per_a <= 0):
            raise ValueError("Finite model rotor, currents and positive Kt required")
        if (observed_pair is not None and
                (not isinstance(observed_pair, (tuple, list)) or
                 len(observed_pair) != 2 or
                 any(type(x) is not int or x not in (0, 1, 2)
                     for x in observed_pair) or
                 observed_pair[0] == observed_pair[1])):
            raise ValueError("Actual observed source/return must be distinct phases")
        theta = math.degrees(electrical_rad) % 360.0
        if self.last_wrapped_deg is None:
            self.unwrapped_deg = theta
            self.origin_deg = theta
        else:
            delta = _shortest_deg(theta - self.last_wrapped_deg)
            if abs(delta) >= 175.0:
                raise ValueError(
                    "Original WFI electrical angle could not be safely unwrapped")
            self.unwrapped_deg += delta
        expected_pair = ORIGINAL_REL17_ROUTE[guest_step][1]
        target_deg = _source_field_target_deg(guest_step)
        error_deg = _shortest_deg(theta - target_deg)
        sin_basis = tuple(math.sin(electrical_rad + d) for d in OFFSETS)
        torque_nm = torque_constant_nm_per_a * sum(
            i * b for i, b in zip(phase_currents_a, sin_basis))
        model_advance = self.unwrapped_deg - self.origin_deg
        guest_advance = 60.0 * completed_sectors
        slip = guest_advance - model_advance
        matched = (observed_pair is not None and
                   tuple(observed_pair) == tuple(expected_pair))
        snapshot = {
            "native_wfi_visit": wfi_visit,
            "native_integrated_ns": integrated_ns,
            "completed_guest_sectors": completed_sectors,
            "guest_step": guest_step,
            "guest_source_return": list(expected_pair),
            "observed_source_return": (list(observed_pair)
                                        if observed_pair is not None else None),
            "observed_pair_matches_step": matched,
            "electrical_angle_deg": theta,
            "unwrapped_electrical_angle_deg": self.unwrapped_deg,
            "rotor_advance_since_first_wfi_deg": model_advance,
            "guest_commanded_advance_deg": guest_advance,
            "commanded_minus_rotor_advance_deg": slip,
            "source_field_max_positive_torque_angle_deg": target_deg,
            "rotor_minus_source_field_angle_deg": error_deg,
            "actual_current_vector_torque_nm": torque_nm,
            "mechanical_rpm": mechanical_rpm,
        }
        if completed_sectors > self.last_sectors:
            advance = (None if self.last_sector_rotor_deg is None else
                       self.unwrapped_deg - self.last_sector_rotor_deg)
            self.sector_checkpoints.append({
                **snapshot,
                "rotor_advance_since_previous_observed_sector_deg": advance,
                "note": "WFI_AFTER_GUEST_SERVICE_NOT_ATOMIC_CAP1_ANGLE",
            })
            self.last_sector_rotor_deg = self.unwrapped_deg
        if completed_sectors >= 6:
            self.post_six_samples += 1
            self.negative_torque_samples += torque_nm < -1e-9
            self.reverse_rpm_samples += mechanical_rpm <= -self.significant_rpm
            self.field_error_gt_90_samples += abs(error_deg) > 90.0
            self.source_pair_mismatch_samples += not matched
            self.max_abs_slip_deg = max(self.max_abs_slip_deg, abs(slip))
            sign = (1 if mechanical_rpm >= self.significant_rpm else
                    -1 if mechanical_rpm <= -self.significant_rpm else 0)
            if sign:
                if self.last_sign and sign != self.last_sign:
                    reversal = {**snapshot, "old_sign": self.last_sign,
                                "new_sign": sign}
                    if self.first_direction_reversal is None:
                        self.first_direction_reversal = reversal
                    if len(self.reversal_checkpoints) < 8:
                        self.reversal_checkpoints.append(reversal)
                self.last_sign = sign
        self.last_snapshot = snapshot
        self.last_wrapped_deg = theta
        self.last_visit = wfi_visit
        self.last_time_ns = integrated_ns
        self.last_sectors = completed_sectors
        return snapshot

    def result(self):
        return {
            "scope": "SIM_ONLY_UNCALIBRATED_ORIGINAL_GUEST_WFI_PHASE_SLIP",
            "diagnostic_not_strict_acceptance": True,
            "wfi_angle_unwrap_assumption": "LESS_THAN_180_DEGREES_PER_GUEST_WFI",
            "guest_source_route": "PINNED_ORIGINAL_REL17",
            "actual_observed_guest_wfi_samples": self.last_visit,
            "post_six_sector_wfi_samples": self.post_six_samples,
            "negative_electromagnetic_torque_wfi_samples": self.negative_torque_samples,
            "negative_mechanical_rpm_wfi_samples": self.reverse_rpm_samples,
            "source_field_error_gt_90_deg_wfi_samples": self.field_error_gt_90_samples,
            "source_pair_mismatch_wfi_samples": self.source_pair_mismatch_samples,
            "max_abs_guest_vs_rotor_advance_slip_deg": self.max_abs_slip_deg,
            "first_direction_reversal": self.first_direction_reversal,
            "first_eight_reversal_checkpoints": self.reversal_checkpoints,
            "observed_sector_checkpoints": self.sector_checkpoints,
            "last_observation": self.last_snapshot,
            "original_guest_register_or_irq_writes": False,
            "motor_parameters_changed": False,
            "original_firmware_or_strict_gate_qualified": False,
            "hardware_stability_qualified": False,
        }
