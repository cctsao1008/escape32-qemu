#!/usr/bin/env python3
"""G13B3G: prove unchanged Rel17 rejected a real *early* BEMF edge.

This is a strict negative control: the original ELF must have received
an actual native ECAP1 CAP1/IRQ event, and yet have rejected its timing
WITHOUT scheduling the next commutation and WITHOUT disarming BEMF.
The host may read original SRAM but must not write firmware state.
This does not qualify any accepted/closed-loop motor commutation.
"""
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class NativeEarlyEdgeRejection:
    first_cap1_ticks: int
    original_crossing_epoch_ticks: int
    calibrated_ticks_per_ms: int
    actual_capture_us: int
    original_rel17_ival_us: int
    minimum_accepted_capture_us: int
    original_guest_rejected_before: int
    original_guest_rejected_after: int
    native_timg12_scheduled_before: int
    native_timg12_scheduled_after: int
    native_bemf_armed_after: bool
    native_selected_code_after: int
    reason: str = "ORIGINAL_REL17_EARLY_BEMF_REJECTED_PRESERVED_ARM"

    def to_dict(self):
        return asdict(self)


def prove_original_early_rejection(*, cap1_ticks: int, epoch_ticks: int,
                                   ticks_per_ms: int, original_ival_us: int,
                                   rejected_before: int, rejected_after: int,
                                   scheduled_before: int, scheduled_after: int,
                                   armed_after: int, selected_after: int,
                                   selected_before: int,
                                   epoch_valid_before: int
                                   ) -> NativeEarlyEdgeRejection:
    if not (0 <= cap1_ticks <= 0xffffffff and
            0 <= epoch_ticks <= 0xffffffff and
            ticks_per_ms == 200000 and
            epoch_valid_before == 1 and
            0 < original_ival_us < 0x80000000):
        raise AssertionError("Unqualified original ECAP/Rel17 timing inputs")
    elapsed_ticks = (cap1_ticks - epoch_ticks) & 0xffffffff
    # Do not permit a timestamp from a stale epoch or 32-bit ambiguity.
    if elapsed_ticks == 0 or elapsed_ticks >= 0x80000000:
        raise AssertionError("Native CAP1 not after qualified crossing epoch")
    # Exact nearest-us conversion from motor_bemf_event_plan.c, not
    # an invented capture duration.
    capture_us = (elapsed_ticks * 1000 + ticks_per_ms//2)//ticks_per_ms
    minimum = original_ival_us >> 1
    if minimum <= 0 or capture_us >= minimum:
        raise AssertionError("Native edge not earlier than Rel17 accept threshold")
    if rejected_after != rejected_before + 1:
        raise AssertionError("Original firmware rejected_events did not increment")
    if scheduled_before != scheduled_after:
        raise AssertionError("Native TIMG12 scheduled; no pure early rejection proof")
    if armed_after != 1 or selected_after != selected_before:
        raise AssertionError("Early edge improperly disarmed or changed original phase")
    if selected_after not in (1, 2, 3, 5, 6, 7):
        raise AssertionError("Original selected BEMF phase invalid")
    return NativeEarlyEdgeRejection(
        first_cap1_ticks=cap1_ticks, original_crossing_epoch_ticks=epoch_ticks,
        calibrated_ticks_per_ms=ticks_per_ms,
        actual_capture_us=capture_us,
        original_rel17_ival_us=original_ival_us,
        minimum_accepted_capture_us=minimum,
        original_guest_rejected_before=rejected_before,
        original_guest_rejected_after=rejected_after,
        native_timg12_scheduled_before=scheduled_before,
        native_timg12_scheduled_after=scheduled_after,
        native_bemf_armed_after=True,
        native_selected_code_after=selected_after)
