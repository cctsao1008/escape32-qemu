"""Read-only original Guest six-output PWM commutation functional audit.

This is a phase-order and Guest-WFI-BRACKETED timing oracle. It is NOT a
nanosecond-accurate MCPWM edge trace, motor physics, or an analog pin measure.

The expected bridge pair is decoded from the pinned Rel17 source commutation
table, independently of Guest selected_code and scripted BEMF polarity. Every
observed transition must be backed by Guest TIMG12 service and must settle to
the source-expected pair on the six physical PWM observer channels.
"""
from __future__ import annotations

from tools.native_closed_loop_audit import ORIGINAL_REL17_ROUTE
from tools.native_power_path_qualification import qualify_cross_phase_bridge


class FunctionalSixPhaseAudit:
    def __init__(self, *, max_sectors=20000, settle_limit_ns=750_000):
        if (type(max_sectors) is not int or not 6 <= max_sectors <= 100000 or
                type(settle_limit_ns) is not int or
                not 62500 <= settle_limit_ns <= 10_000_000):
            raise ValueError("Invalid bounded original Guest audit limits")
        self.max_sectors = max_sectors
        self.settle_limit_ns = settle_limit_ns
        self.previous = None
        self.pending = None
        self.sectors = []
        self.issues = []
        self.phase_pairs_seen = set()
        self.last_time_ns = None
        self.observed_wfi = 0
        self.idle_wfi = 0
        self.startup_seeds = []
        # Read-only diagnosis, bounded independently of the potentially long
        # 110 s scenario. One expiration must never become a false PASS.
        self.failed_commutations = []
        self.failed_commutation_total = 0
        self.observed_step_changes = 0

    @staticmethod
    def _pwm_diagnostic(pwm, *, guest_time_ns: int):
        """Preserve actual six-pad observer readings, including invalid ones."""
        keys = ("six_high_ticks", "period_ticks", "valid_mask", "pwm_status",
                "gate_and_pads", "pwm_powered", "pwm_tbclk_enabled",
                "physical_ost2", "physical_ost3", "native_pwm_valid",
                "nonzero_phase_voltage_command", "acceptable_for_plant",
                "reason")
        r = {"wfi_ns": guest_time_ns}
        for key in keys:
            value = getattr(pwm, key, None)
            if isinstance(value, tuple):
                value = list(value)
            r[key] = value
        if (getattr(pwm, "native_pwm_valid", False) and
                getattr(pwm, "period_ticks", 0) > 0):
            bridge = qualify_cross_phase_bridge(
                pwm.six_high_ticks, period_ticks=pwm.period_ticks,
                gate_trip_qualified=bool(pwm.acceptable_for_plant))
            r["actual_upper_phase_indices"] = list(bridge.upper_phase_indices)
            r["actual_lower_phase_indices"] = list(bridge.lower_phase_indices)
            r["actual_distinct_phase_pairs"] = [
                list(pair) for pair in bridge.different_phase_pairs]
        return r

    def _record_failed(self, entry, reason):
        self.failed_commutation_total += 1
        if len(self.failed_commutations) < 16:
            self.failed_commutations.append({
                "reason": reason,
                "old_guest_step": entry["old_guest_step"],
                "new_guest_step": entry["new_guest_step"],
                "expected_source_to_return": entry["expected_source_to_return"],
                "commutation_wfi_bracket_ns":
                    entry["commutation_wfi_bracket_ns"],
                "pwm_observation_count": entry["pwm_observation_count"],
                "first_pwm_observation": entry["first_pwm_observation"],
                "last_pwm_observation": entry["last_pwm_observation"],
                "note": "Original PWM readings at Guest WFI; no exact edge timestamp",
            })

    def needs_pwm(self, step: int) -> bool:
        """Read the six output registers only near an actual commutation."""
        return (self.pending is not None or
                (self.previous is not None and
                 1 <= step <= 6 and
                 1 <= self.previous["step"] <= 6 and
                 step != self.previous["step"]))

    def observe(self, *, guest_time_ns: int, guest_step: int,
                guest_serviced: int, guest_captured: int,
                pwm=None, guest_throttle=None):
        if (type(guest_time_ns) is not int or guest_time_ns < 0 or
                type(guest_step) is not int or not 0 <= guest_step <= 6 or
                type(guest_serviced) is not int or guest_serviced < 0 or
                type(guest_captured) is not int or guest_captured < 0 or
                (guest_throttle is not None and
                 (type(guest_throttle) is not int or guest_throttle < 0))):
            raise ValueError("Invalid original Guest WFI snapshot")
        now = dict(time_ns=guest_time_ns, step=guest_step,
                   serviced=guest_serviced, captured=guest_captured)
        old = self.previous
        if guest_step == 0:
            self.idle_wfi += 1
        if old is not None:
            if (guest_time_ns < old["time_ns"] or
                    guest_serviced < old["serviced"] or
                    guest_captured < old["captured"]):
                self.issues.append("ORIGINAL_GUEST_TIME_OR_COUNTER_REGRESSION")
            if guest_step != old["step"]:
                self.observed_step_changes += 1
            if old["step"] == 0 and guest_step != 0:
                # Original Rel17 starts with step=0 at idle. Its initial
                # 0->active choice is startup, not feedback TIMG12.
                # Observe it, but NEVER credit it as a commutation sector.
                if len(self.startup_seeds) < 64:
                    self.startup_seeds.append({
                        "wfi_ns": guest_time_ns,
                        "initial_guest_step": guest_step,
                        "guest_serviced": guest_serviced})
            elif old["step"] != 0 and guest_step == 0:
                # A neutral command can legitimately stop the motor. A
                # powered-command shutdown must never pass unnoticed.
                if guest_throttle is not None and guest_throttle > 1:
                    self.issues.append("UNEXPECTED_GUEST_IDLE_WITH_NONZERO_THROTTLE")
                if self.pending is not None:
                    self.issues.append("COMMUTATION_INTERRUPTED_BY_IDLE")
                    self.pending = None
            elif guest_step != old["step"]:
                if self.pending is not None:
                    self.issues.append("PREVIOUS_COMMUTATION_NEVER_SETTLED")
                    self._record_failed(self.pending,
                                        "SUPERSEDED_BY_NEXT_GUEST_STEP")
                    self.pending = None
                if len(self.sectors) >= self.max_sectors:
                    self.issues.append("BOUNDED_SECTOR_STORAGE_EXHAUSTED")
                elif (guest_step != old["step"] % 6 + 1 or
                      guest_serviced <= old["serviced"] or
                      guest_serviced - old["serviced"] != 1):
                    self.issues.append("UNSUPPORTED_GUEST_STEP_OR_TIMG12_SEQUENCE")
                else:
                    pair = ORIGINAL_REL17_ROUTE[guest_step][1]
                    self.pending = dict(
                        old_guest_step=old["step"], new_guest_step=guest_step,
                        serviced_before=old["serviced"],
                        serviced_after=guest_serviced,
                        commutation_wfi_bracket_ns=[
                            old["time_ns"], guest_time_ns],
                        expected_source_to_return=list(pair),
                        pwm_settled_wfi_ns=None,
                        measured_six_high_ticks=None,
                        measured_period_ticks=None,
                        observed_transient_pairs=[],
                        pwm_observation_count=0,
                        first_pwm_observation=None,
                        last_pwm_observation=None)
        if self.pending is not None:
            p = self.pending
            if guest_time_ns - p["commutation_wfi_bracket_ns"][1] > self.settle_limit_ns:
                self.issues.append("PWM_DID_NOT_SETTLE_WITHIN_WFI_WINDOW")
                self._record_failed(self.pending,
                                    "NO_EXPECTED_PAIR_WITHIN_750US_WINDOW")
                self.pending = None
            elif pwm is not None:
                actual_snapshot = self._pwm_diagnostic(
                    pwm, guest_time_ns=guest_time_ns)
                p["pwm_observation_count"] += 1
                if p["first_pwm_observation"] is None:
                    p["first_pwm_observation"] = actual_snapshot
                p["last_pwm_observation"] = actual_snapshot
                if (not pwm.native_pwm_valid or pwm.period_ticks <= 0 or
                        not pwm.gate_and_pads or
                        not pwm.pwm_powered or not pwm.pwm_tbclk_enabled or
                        pwm.physical_ost2 or pwm.physical_ost3):
                    if len(p["observed_transient_pairs"]) < 8:
                        p["observed_transient_pairs"].append(
                            {"wfi_ns": guest_time_ns,
                             "reason": "PWM_NOT_QUALIFIED_AT_WFI"})
                else:
                    bridge = qualify_cross_phase_bridge(
                        pwm.six_high_ticks,
                        period_ticks=pwm.period_ticks,
                        gate_trip_qualified=True)
                    actual = bridge.different_phase_pairs
                    expected = tuple(p["expected_source_to_return"])
                    if (bridge.upper_phase_indices == (expected[0],) and
                            bridge.lower_phase_indices == (expected[1],) and
                            actual == (expected,) and
                            pwm.acceptable_for_plant):
                        p["pwm_settled_wfi_ns"] = guest_time_ns
                        p["measured_six_high_ticks"] = list(pwm.six_high_ticks)
                        p["measured_period_ticks"] = pwm.period_ticks
                        self.sectors.append(p)
                        self.phase_pairs_seen.add(expected)
                        self.pending = None
                    else:
                        if len(p["observed_transient_pairs"]) < 8:
                            p["observed_transient_pairs"].append({
                                "wfi_ns": guest_time_ns,
                                "upper_phases": list(bridge.upper_phase_indices),
                                "lower_phases": list(bridge.lower_phase_indices),
                                "reason": "TRANSITION_OR_MISMATCH_NOT_YET_SETTLED"})
        self.previous = now
        self.last_time_ns = guest_time_ns
        self.observed_wfi += 1

    def report(self) -> dict:
        unique_steps = {s["new_guest_step"] for s in self.sectors}
        complete_cycle = len(self.sectors) >= 6 and len(unique_steps) == 6
        issues = list(dict.fromkeys(self.issues))
        # A scenario may stop between TIMG12 service and the next carrier
        # zero. Preserve that incomplete last bracket but never convert it
        # into a fabricated observed vector or poison previous proved sectors.
        if not complete_cycle:
            issues.append("NO_COMPLETE_POWERED_SIX_STEP_SEQUENCE")
        return {
            "scope": "ORIGINAL_GUEST_WFI_BRACKETED_MCPWM4_SIX_PAD_FUNCTIONAL",
            "source": "ORIGINAL_GUEST_TIMG12_STEP_AND_INDEPENDENT_PWM_READS",
            "expected_phase_pairs_source":
                "PINNED_REL17_COMMUTATION_SEQUENCE_NOT_GUEST_COMPARATOR_CODE",
            "sample_clock": "ORIGINAL_GUEST_SYSTICK_16KHZ",
            "exact_mcpwm_edge_timestamps_qualified": False,
            "phase_independent_bemf_source_qualified": False,
            "electrical_gate_driver_or_motor_qualified": False,
            "observed_wfi": self.observed_wfi,
            "observed_idle_wfi": self.idle_wfi,
            "observed_guest_step_changes": self.observed_step_changes,
            "failed_commutation_total": self.failed_commutation_total,
            "first_failed_commutations": self.failed_commutations,
            "startup_seeds": self.startup_seeds,
            "settled_commutation_count": len(self.sectors),
            "all_six_guest_steps_observed_with_expected_pwm": complete_cycle,
            "distinct_source_to_return_pairs": [
                list(x) for x in sorted(self.phase_pairs_seen)],
            "sectors": self.sectors,
            "pending": self.pending,
            "issues": issues,
            "status": ("PASS_WFI_BRACKETED_SIX_PHASE_FUNCTIONAL_ONLY"
                       if complete_cycle and not issues else
                       "OPEN_OR_FAIL_SIX_PHASE_AUDIT"),
        }
