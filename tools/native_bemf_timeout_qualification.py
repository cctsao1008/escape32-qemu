#!/usr/bin/env python3
"""G13B3I: read-only native no-valid-BEMF timeout qualification.

The only clock is original ECAP1 TSCTR calibrated to 200MHz by the
unmodified ESCape32 ELF. No guest SRAM, IRQ, PWM, ECAP, comparator,
fault or QEMU stimulus is written to synthesize a timeout.
"""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class NativeNoFeedbackTimeout:
    native_epoch: int
    native_timeout_ticks: int
    native_capture_end_ticks: int
    elapsed_since_epoch_ticks: int
    original_capture_before: int
    original_capture_after: int
    original_rejected_before: int
    original_rejected_after: int
    original_timg12_cancelled_before: int
    original_timg12_cancelled_after: int
    original_ertm_after: int
    original_bemf_disarmed: bool
    simulator_bemf_valid_inputs: int
    physical_trip_flags: int
    reason: str = "ORIGINAL_SYSTICK_ECAP_NO_FEEDBACK_TIMEOUT"

    def to_dict(self):
        return asdict(self)


def prove_native_no_feedback_timeout(*, epoch: int, timeout_ticks: int,
                                     cap_end_ticks: int, armed_before: int,
                                     armed_after: int,
                                     epoch_valid_before: int,
                                     epoch_valid_after: int,
                                     ticks_per_ms: int,
                                     captured_before: int,
                                     captured_after: int,
                                     rejected_before: int,
                                     rejected_after: int,
                                     cancelled_before: int,
                                     cancelled_after: int,
                                     ertm_after: int,
                                     simulator_bemf_words: tuple[int,int,int],
                                     physical_tz_flags: int
                                     ) -> NativeNoFeedbackTimeout:
    if (not 0 <= epoch <= 0xffffffff or
            not 0 <= cap_end_ticks <= 0xffffffff or
            not 0 < timeout_ticks < 0x80000000 or
            ticks_per_ms != 200000 or
            armed_before != 1 or armed_after != 0 or
            epoch_valid_before != 1 or epoch_valid_after != 0):
        raise AssertionError("Original native BEMF arm/clock/timeout invalid")
    elapsed = (cap_end_ticks-epoch) & 0xffffffff
    if not timeout_ticks <= elapsed <= timeout_ticks + 200000:
        raise AssertionError("ECAP time did not reach bounded native timeout")
    if captured_after != captured_before or rejected_after != rejected_before:
        raise AssertionError("A real comparator event occurred: not no-BEMF")
    if cancelled_after <= cancelled_before:
        raise AssertionError("Original TIMG12 cancellation was not observed")
    if ertm_after != 100000000:
        raise AssertionError("Original Rel17 BEMF timeout policy did not reset ertm")
    if len(simulator_bemf_words) != 3 or any(
            word & ~0x10fff or word & 0x10000 for word in simulator_bemf_words):
        raise AssertionError("QEMU BEMF had a valid or malformed voltage sample")
    if physical_tz_flags & 0x60000:
        raise AssertionError("Physical trip intervened in no-BEMF timeout")
    return NativeNoFeedbackTimeout(
        native_epoch=epoch,
        native_timeout_ticks=timeout_ticks,
        native_capture_end_ticks=cap_end_ticks,
        elapsed_since_epoch_ticks=elapsed,
        original_capture_before=captured_before,
        original_capture_after=captured_after,
        original_rejected_before=rejected_before,
        original_rejected_after=rejected_after,
        original_timg12_cancelled_before=cancelled_before,
        original_timg12_cancelled_after=cancelled_after,
        original_ertm_after=ertm_after,
        original_bemf_disarmed=True,
        simulator_bemf_valid_inputs=0,
        physical_trip_flags=physical_tz_flags)
