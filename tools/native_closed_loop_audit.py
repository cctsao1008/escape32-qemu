#!/usr/bin/env python3
"""Causal native CAP1 -> original TIMG12 -> powered six-sector audit.

Host cannot create any of these events. Real guest/QTest reader supplies
original counters, ECAP timestamps and physically measured six PWM outputs.
A host-only test of this logic never qualifies original firmware.
"""
from dataclasses import dataclass, asdict
from .native_power_path_qualification import qualify_cross_phase_bridge


@dataclass(frozen=True)
class NativeSectorEvidence:
    accepted_cap1_ticks: int
    serviced_ecap_ticks: int
    guest_step_before: int
    guest_step_after: int
    guest_selected_code_before: int
    guest_selected_code_after: int
    prior_source_return: tuple[int, int]
    next_source_return: tuple[int, int]
    pwm_before: tuple[int, ...]
    pwm_after: tuple[int, ...]

    def to_dict(self):
        return asdict(self)


class NativeClosedLoopAudit:
    """Original guest owns every accepted capture, timer and new PWM vector."""

    def __init__(self, *, required_sectors=6):
        if not 6 <= required_sectors <= 24:
            raise ValueError("Require at least one full six-step cycle")
        self.required_sectors = required_sectors
        self.last = None
        self.pending = None
        self.sectors = []
        self.early_rejections = 0
        self.qualified_power_snapshots = 0
        self.reason = "NO_NATIVE_POWERED_FEEDBACK_YET"

    @property
    def qualified(self):
        return len(self.sectors) >= self.required_sectors

    def ingest(self, *, ecap_ticks, cap1_ticks, captured, rejected,
               scheduled, serviced, step, selected_code, pwm_high,
               pwm_period, gate_trip_qualified, rpm):
        if not 0 <= ecap_ticks <= 0xffffffff or not 0 <= cap1_ticks <= 0xffffffff:
            raise AssertionError("Native ECAP ticks invalid")
        if any(not 0 <= x <= 0xffffffff for x in
               (captured, rejected, scheduled, serviced)):
            raise AssertionError("Original counters invalid")
        if not 1 <= step <= 6 or selected_code not in (1, 2, 3, 5, 6, 7):
            raise AssertionError("Original sixstep/phase invalid")
        path = qualify_cross_phase_bridge(
            pwm_high, period_ticks=pwm_period,
            gate_trip_qualified=gate_trip_qualified)
        if path.qualifies_necessary_two_terminal_drive:
            self.qualified_power_snapshots += 1
        now = dict(ecap_ticks=ecap_ticks, cap1_ticks=cap1_ticks,
                   captured=captured, rejected=rejected, scheduled=scheduled,
                   serviced=serviced, step=step, selected_code=selected_code,
                   pwm_high=tuple(pwm_high),
                   power_pairs=path.different_phase_pairs,
                   path_ok=path.qualifies_necessary_two_terminal_drive, rpm=rpm)
        if self.last is None:
            self.last = now
            return
        old = self.last
        delta = (ecap_ticks - old["ecap_ticks"]) & 0xffffffff
        if delta == 0 or delta >= 0x80000000:
            raise AssertionError("Native ECAP time not monotonic")
        for field in ("captured", "rejected", "scheduled", "serviced"):
            if now[field] < old[field]:
                raise AssertionError("Original guest counter backwards: " + field)
            if now[field] - old[field] > 1:
                raise AssertionError("Missed multiple guest events: " + field)
        if captured > old["captured"]:
            if cap1_ticks == old["cap1_ticks"]:
                raise AssertionError("Original IRQ changed without genuine CAP1")
            if scheduled > old["scheduled"] and rejected == old["rejected"]:
                if self.pending is not None:
                    raise AssertionError("New accepted CAP1 before previous powered sector")
                self.pending = dict(
                    accepted_cap1_ticks=cap1_ticks,
                    pre_step=old["step"], pre_selected=old["selected_code"],
                    pre_pwm=old["pwm_high"],
                    pre_pair=old["power_pairs"][0] if old["power_pairs"] else None,
                    original_serviced_before=old["serviced"],
                    service_tick=None)
                self.reason = "WAIT_ORIGINAL_TIMG12_SERVICE"
            elif rejected > old["rejected"] and scheduled == old["scheduled"]:
                self.early_rejections += 1
                self.reason = "ORIGINAL_REL17_EARLY_BEMF_REJECTION"
            else:
                raise AssertionError("CAP1 schedule/reject original policy mismatch")
        elif scheduled > old["scheduled"]:
            # An independent bootstrap timer does not count as feedback.
            self.reason = "NON_FEEDBACK_NATIVE_SCHEDULE"
        if self.pending is not None:
            pending = self.pending
            if serviced > pending["original_serviced_before"]:
                if pending["service_tick"] is None:
                    pending["service_tick"] = ecap_ticks
                if (now["step"] != (pending["pre_step"] % 6) + 1 or
                    now["selected_code"] == pending["pre_selected"]):
                    raise AssertionError("Original TIMG12 serviced without nextstep")
                if (now["path_ok"] and pending["pre_pair"] is not None and
                    now["power_pairs"] and
                    now["power_pairs"][0] != pending["pre_pair"] and
                    now["pwm_high"] != pending["pre_pwm"]):
                    if not isinstance(rpm, (int, float)) or rpm == 0:
                        raise AssertionError("No plant RPM at original powered step")
                    self.sectors.append(NativeSectorEvidence(
                        accepted_cap1_ticks=pending["accepted_cap1_ticks"],
                        serviced_ecap_ticks=pending["service_tick"],
                        guest_step_before=pending["pre_step"],
                        guest_step_after=now["step"],
                        guest_selected_code_before=pending["pre_selected"],
                        guest_selected_code_after=now["selected_code"],
                        prior_source_return=pending["pre_pair"],
                        next_source_return=now["power_pairs"][0],
                        pwm_before=pending["pre_pwm"], pwm_after=now["pwm_high"]))
                    self.pending = None
                    self.reason = "POWERED_ORIGINAL_NATIVE_SECTOR_COMPLETED"
                else:
                    self.reason = "ORIGINAL_TIMG12_SERVED_NO_PHYSICAL_VECTOR_YET"
        self.last = now

    def result(self):
        return dict(qualified=self.qualified,
                    required_sectors=self.required_sectors,
                    completed_feedback_powered_sectors=len(self.sectors),
                    original_early_rejections=self.early_rejections,
                    powered_pwm_samples=self.qualified_power_snapshots,
                    sector_evidence=[s.to_dict() for s in self.sectors],
                    reason=self.reason)
