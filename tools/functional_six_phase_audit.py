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

    def needs_pwm(self, step: int) -> bool:
        """Read the six output registers only near an actual commutation."""
        return (self.pending is not None or
                (self.previous is not None and
                 step != self.previous["step"]))

    def observe(self, *, guest_time_ns: int, guest_step: int,
                guest_serviced: int, guest_captured: int,
                pwm=None):
        if (type(guest_time_ns) is not int or guest_time_ns < 0 or
                type(guest_step) is not int or not 1 <= guest_step <= 6 or
                type(guest_serviced) is not int or guest_serviced < 0 or
                type(guest_captured) is not int or guest_captured < 0):
            raise ValueError("Invalid original Guest WFI snapshot")
        now = dict(time_ns=guest_time_ns, step=guest_step,
                   serviced=guest_serviced, captured=guest_captured)
        old = self.previous
        if old is not None:
            if (guest_time_ns < old["time_ns"] or
                    guest_serviced < old["serviced"] or
                    guest_captured < old["captured"]):
                self.issues.append("ORIGINAL_GUEST_TIME_OR_COUNTER_REGRESSION")
            if guest_step != old["step"]:
                if self.pending is not None:
                    self.issues.append("PREVIOUS_COMMUTATION_NEVER_SETTLED")
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
                        observed_transient_pairs=[])
        if self.pending is not None:
            p = self.pending
            if guest_time_ns - p["commutation_wfi_bracket_ns"][1] > self.settle_limit_ns:
                self.issues.append("PWM_DID_NOT_SETTLE_WITHIN_WFI_WINDOW")
                self.pending = None
            elif pwm is not None:
                if (not pwm.native_pwm_valid or pwm.period_ticks <= 0 or
                        not pwm.gate_and_pads or
                        not pwm.pwm_powered or not pwm.pwm_tbclk_enabled or
                        pwm.physical_ost2 or pwm.physical_ost3):
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
        if self.pending is not None:
            issues.append("LAST_COMMUTATION_NOT_YET_SETTLED")
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
