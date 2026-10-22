#!/usr/bin/env python3
"""G13B3F native event causal audit.

Original QEMU CMPSS0 filter -> ECAP1 CAP1 can happen ONLY when a real
selected-phase comparator voltage crosses the guest-owned DAC threshold
with the original selected polarity. Require original guest ISR's
captured_events counter to increment; neither QTest nor host writes
CAP1, ECEINT, ECFLG, ISR flags, guest SRAM, throttle, PWM or Gate.
"""
from dataclasses import dataclass, asdict
from .native_bemf_injection import NativeBemfStimulus


@dataclass(frozen=True)
class NativeBemfCaptureEvidence:
    first_event_sample_index: int
    selected_code: int
    selected_phase: int
    comparator_threshold: int
    comparator_edge: str
    crossing_input_code_before: int
    crossing_input_code_after: int
    injection_timestamp_ticks: int
    native_ecap_cap1_ticks: int
    observed_native_tsctr_ticks: int
    original_guest_capture_count_before: int
    original_guest_capture_count_after: int
    irq_evidence: str

    def to_dict(self):
        return asdict(self)


def prove_capture_from_native_samples(records: list[NativeBemfStimulus], *,
                                      cap1_before: int, cap1_after: int,
                                      native_now: int,
                                      guest_count_before: int,
                                      guest_count_after: int
                                      ) -> NativeBemfCaptureEvidence:
    if (guest_count_after <= guest_count_before or
            guest_count_before < 0 or cap1_after == cap1_before or
            not 0 <= cap1_after <= 0xffffffff or
            not 0 <= native_now <= 0xffffffff):
        raise AssertionError("No original guest IRQ counter + real CAP1 change")
    if len(records) < 2:
        raise AssertionError("Insufficient plant-derived BEMF voltage history")
    for earlier, later in zip(records, records[1:]):
        if (earlier.selected_code != later.selected_code or
                earlier.selected_phase != later.selected_phase or
                earlier.active_dac_code != later.active_dac_code):
            continue
        phase = later.selected_phase
        if phase not in (0, 1, 2):
            continue
        old = earlier.sample_words[phase] & 0xfff
        new = later.sample_words[phase] & 0xfff
        dac = later.active_dac_code
        rising = bool(later.selected_code & 4)
        crossed = ((old <= dac and new > dac) if rising
                   else (old > dac and new <= dac))
        if not crossed:
            continue
        delta = (cap1_after - later.native_ecap_ticks) & 0xffffffff
        allowed = (native_now - later.native_ecap_ticks) & 0xffffffff
        if not 0 <= delta <= allowed or allowed >= 0x80000000:
            raise AssertionError(
                "CAP1 not timestamped after plant voltage crossing injection")
        return NativeBemfCaptureEvidence(
            first_event_sample_index=later.sample_index,
            selected_code=later.selected_code,
            selected_phase=phase,
            comparator_threshold=dac,
            comparator_edge="RISING" if rising else "FALLING",
            crossing_input_code_before=old,
            crossing_input_code_after=new,
            injection_timestamp_ticks=later.native_ecap_ticks,
            native_ecap_cap1_ticks=cap1_after,
            observed_native_tsctr_ticks=native_now,
            original_guest_capture_count_before=guest_count_before,
            original_guest_capture_count_after=guest_count_after,
            irq_evidence="ORIGINAL_GUEST_captured_events_INCREMENTED"
        )
    raise AssertionError("No phase/DAC/polarity crossing in actual plant samples")
