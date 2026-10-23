#!/usr/bin/env python3
"""Causal native CAP1 -> original TIMG12 -> powered six-sector audit.

Host cannot create any of these events. Real guest/QTest reader supplies
original counters, ECAP timestamps and physically measured six PWM outputs.
A host-only test of this logic never qualifies original firmware.
"""
from dataclasses import dataclass, asdict
from .native_power_path_qualification import qualify_cross_phase_bridge


# Canonical original firmware: ESCape32/src/commutation.h at pinned
# b0204670515d2de0b2480b52273038f1ee13d30a.
# Original src/main.c computes m=x>>3, comparator_code=m>>3, and
# passes (x&m),(~x&m) as the actual sixstep phase masks.
# Do NOT infer the COMP route from a rotor phase order or a reversed
# handwritten BEMF table. In particular steps 3..6 are 6,1,7,2,
# not 7,2,6,1. This is a strict original-source correspondence gate.
REL17_COMMUTATION_SEQUENCE = (0x175, 0xd9, 0x1ab, 0x72, 0x1de, 0xac)


def _original_rel17_route():
    route = [None]
    for x in REL17_COMMUTATION_SEQUENCE:
        m = x >> 3
        upper = (x & m) & 0x7
        lower = ((~x) & m) & 0x7
        if (upper.bit_count() != 1 or lower.bit_count() != 1 or
                upper & lower or not 1 <= (m >> 3) <= 7):
            raise AssertionError("Pinned original Rel17 sector route invalid")
        route.append((m >> 3,
                      (upper.bit_length() - 1, lower.bit_length() - 1)))
    return tuple(route)


ORIGINAL_REL17_ROUTE = _original_rel17_route()


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
        # Rel17 motor_bemf.c:400 resets rejected_events on native
        # interval rearm. It is NOT a lifetime monotonic counter.
        # Still fail closed on any unexplained decrease.
        self.original_rejection_window_resets = 0
        self.unpowered_native_timg12_steps = 0
        self.qualified_power_snapshots = 0
        self.reason = "NO_NATIVE_POWERED_FEEDBACK_YET"

    @property
    def qualified(self):
        return len(self.sectors) >= self.required_sectors

    def ingest(self, *, ecap_ticks, cap1_ticks, captured, rejected,
               scheduled, serviced, step, selected_code, pwm_high,
               pwm_period, gate_trip_qualified, rpm,
               armed=True, pending_code=0):
        if not 0 <= ecap_ticks <= 0xffffffff or not 0 <= cap1_ticks <= 0xffffffff:
            raise AssertionError("Native ECAP ticks invalid")
        if any(not 0 <= x <= 0xffffffff for x in
               (captured, rejected, scheduled, serviced)):
            raise AssertionError("Original counters invalid")
        # Original Rel17 am13e_app_motor_bemf_stage() temporarily
        # clears selected_code during AQ global-load, then only the
        # native MCPWM ZERO carrier IRQ publishes and arms the next phase.
        # Waiting for this source-authored transient is mandatory.
        route = ORIGINAL_REL17_ROUTE
        if not 1 <= step <= 6 or selected_code not in (0, 1, 2, 3, 5, 6, 7):
            raise AssertionError("Original sixstep/phase invalid")
        if selected_code == 0:
            if armed or pending_code not in (1, 2, 3, 5, 6, 7):
                raise AssertionError("Native BEMF code0 without legitimate pending publication")
        elif selected_code != route[step][0]:
            # A just-serviced original TIMG12 IRQ may leave the new
            # Guest selected_code unpublished until a later real PWM ZERO;
            # old code is allowed only while the Guest is disarmed.
            if armed:
                raise AssertionError("Armed original BEMF phase differs from guest step")
        if pending_code and pending_code not in (1, 2, 3, 5, 6, 7):
            raise AssertionError("Unknown original pending BEMF code")
        path = qualify_cross_phase_bridge(
            pwm_high, period_ticks=pwm_period,
            gate_trip_qualified=gate_trip_qualified)
        if path.qualifies_necessary_two_terminal_drive:
            self.qualified_power_snapshots += 1
        now = dict(ecap_ticks=ecap_ticks, cap1_ticks=cap1_ticks,
                   captured=captured, rejected=rejected, scheduled=scheduled,
                   serviced=serviced, step=step, selected_code=selected_code,
                   armed=bool(armed), pending_code=pending_code,
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
        # Three cumulative original counters must never regress. Rel17's
        # rejected_events is different: am13e_app_motor_bemf_interval_select()
        # resets it when the ORIGINAL TIMG12 nextstep publishes/rearms BEMF.
        # A rejected edge remains rejected: zeroing the interval counter
        # cannot create/credit a sector or hide a missing CAP1/TIMG12.
        for field in ("captured", "scheduled", "serviced"):
            if now[field] < old[field]:
                raise AssertionError("Original guest counter backwards: " + field)
            if now[field] - old[field] > 1:
                raise AssertionError("Missed multiple guest events: " + field)
        if rejected < old["rejected"]:
            expected_step = (old["step"] % 6) + 1
            valid_pending = (
                self.pending is not None and
                self.pending["pre_step"] == old["step"] and
                self.pending["original_serviced_before"] == old["serviced"]
            )
            # TIMG12's source-owned nextstep, not a Host counter reset.
            # An intermediate native carrier-ZERO publication may leave
            # the comparator temporarily disarmed with pending_code.
            source_rearm = (
                rejected == 0 and valid_pending and
                serviced == old["serviced"] + 1 and
                step == expected_step and
                ((selected_code == 0 and not armed and
                  pending_code == route[step][0]) or
                 (selected_code == route[step][0] and armed and
                  pending_code == 0))
            )
            # The pinned Rel17 firmware uses TWO source-owned callbacks:
            #  TIMG12 IRQ: nextstep() -> motor_bemf_stage()
            #             selected_code=0, pending_code=next COMP phase
            #  MCPWM ZERO: motor_bemf_carrier_zero() -> interval_select()
            #             rejected_events=0, selected_code=next phase,
            #             armed=1, pending_code=0
            # When a genuine WFI falls BETWEEN these callbacks, the
            # original rejected counter clears one (or more) observations
            # AFTER the original TIMG12 service and step increment. Such
            # a reset is legal ONLY on that exact Guest stage->publish
            # transition for a previously accepted CAP1. No fabricated
            # elapsed time, Guest IRQ, counter, or firmware state is used.
            pending = self.pending
            deferred_carrier_zero_rearm = (
                rejected == 0 and
                pending is not None and
                pending["service_tick"] is not None and
                old["step"] == (pending["pre_step"] % 6) + 1 and
                old["serviced"] > pending["original_serviced_before"] and
                serviced == old["serviced"] and
                scheduled == old["scheduled"] and
                captured == old["captured"] and
                old["selected_code"] == 0 and
                not old["armed"] and
                old["pending_code"] == route[old["step"]][0] and
                step == old["step"] and
                selected_code == route[step][0] and
                bool(armed) and pending_code == 0
            )
            if not (source_rearm or deferred_carrier_zero_rearm):
                raise AssertionError(
                    "Original guest rejected counter reset WITHOUT "
                    "accepted CAP1->TIMG12 native nextstep BEMF rearm: " +
                    repr({
                        "previous": {k: old[k] for k in
                                     ("captured", "rejected", "scheduled",
                                      "serviced", "step", "selected_code",
                                      "armed", "pending_code")},
                        "current": {k: now[k] for k in
                                    ("captured", "rejected", "scheduled",
                                     "serviced", "step", "selected_code",
                                     "armed", "pending_code")},
                        "accepted_cap1_pending": pending,
                        "immediate_rearm": bool(source_rearm),
                        "carrier_zero_deferred_rearm":
                            bool(deferred_carrier_zero_rearm),
                    }))
            self.original_rejection_window_resets += 1
        elif rejected - old["rejected"] > 1:
            raise AssertionError("Missed multiple guest events: rejected")
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
                if now["step"] != (pending["pre_step"] % 6) + 1:
                    raise AssertionError("Original TIMG12 serviced without nextstep")
                if pending["pre_pair"] is None:
                    # Early six-step stages can occur before the physical
                    # high-side pulse clears deadtime. This is an original
                    # TIMG12 ISR but NOT a powered commutation. Discard
                    # any expectation that this alone closes the loop.
                    self.unpowered_native_timg12_steps += 1
                    self.pending = None
                    self.reason = "REAL_TIMG12_UNPOWERED_SECTOR_NOT_CREDITED"
                elif (now["path_ok"] and now["power_pairs"] and
                    now["power_pairs"][0] != pending["pre_pair"] and
                    now["pwm_high"] != pending["pre_pwm"] and
                    now["armed"] and now["pending_code"] == 0 and
                    now["selected_code"] == route[now["step"]][0]):
                    if now["power_pairs"] != (route[now["step"]][1],):
                        raise AssertionError("Measured powered PWM not original sixstep vector")
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
                    self.reason = (
                        "WAIT_ORIGINAL_CARRIER_ZERO_BEMF_PUBLICATION_OR_POWERED_VECTOR")
        self.last = now

    def result(self):
        return dict(qualified=self.qualified,
                    required_sectors=self.required_sectors,
                    completed_feedback_powered_sectors=len(self.sectors),
                    original_early_rejections=self.early_rejections,
                    original_rejection_window_resets=self.original_rejection_window_resets,
                    original_unpowered_timg12_steps=self.unpowered_native_timg12_steps,
                    powered_pwm_samples=self.qualified_power_snapshots,
                    sector_evidence=[s.to_dict() for s in self.sectors],
                    reason=self.reason)
