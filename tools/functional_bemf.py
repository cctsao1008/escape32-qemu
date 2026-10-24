#!/usr/bin/env python3
"""Scripted comparator-voltage test stimulus, not a physical motor.

No rotor simulation, no fake ECAP or ISR. Observe original Guest's selected
BEMF phase/edge route, then issue a bounded crossing through the existing
SIM_ONLY U/V/W analog voltage port. Only native Guest owns commutation.
"""
from __future__ import annotations
from dataclasses import dataclass


class FunctionalBemfError(ValueError):
    pass


@dataclass(frozen=True)
class BemfVector:
    elapsed_ns: int
    guest_step: int
    selected_code: int
    phase: int
    crossing_issued: bool
    analog_words: tuple[int, int, int]

    def to_dict(self):
        return {
            "elapsed_guest_ns": self.elapsed_ns,
            "guest_step": self.guest_step,
            "selected_code": self.selected_code,
            "selected_phase": self.phase,
            "crossing_issued": self.crossing_issued,
            "analog_words": list(self.analog_words),
            "scope": "SCRIPTED_SIM_ONLY_COMPARATOR_ANALOG_NOT_MOTOR_PHYSICS"
        }


class FunctionalBemf:
    """Emit repeatable comparator-edge transitions per Guest sector arm.

    Readiness and expected_edge_falling MUST be obtained from the real
    Guest-owned COMP/ECAP register snapshot, not a hardcoded phase table.
    A 50% duty external test waveform periodically offers a crossing at the
    selected native comparator polarity; the original Guest decides whether
    to accept or reject it. No host CAP1/TIMG12 writes or forced IRQs.
    """
    def __init__(self, *, crossing_delay_ns: int = 750_000,
                 amplitude_codes: int = 128):
        if type(crossing_delay_ns) is not int or not 10_000 <= crossing_delay_ns <= 50_000_000:
            raise FunctionalBemfError('crossing_delay_ns must be 10us..50ms')
        if type(amplitude_codes) is not int or not 1 <= amplitude_codes <= 512:
            raise FunctionalBemfError('amplitude_codes must be 1..512')
        self.crossing_delay_ns = crossing_delay_ns
        self.amplitude_codes = amplitude_codes
        self._key = None
        self._start_ns = None
        self._last_words = None
        self.crossings_issued = 0

    def evaluate(self, *, guest_ns: int, guest_step: int, selected_code: int,
                 selected_phase: int, expected_edge_falling: bool,
                 dac_code: int) -> BemfVector:
        if (type(guest_ns) is not int or guest_ns < 0 or
                type(guest_step) is not int or not 1 <= guest_step <= 6 or
                type(selected_code) is not int or not 1 <= selected_code <= 7 or
                type(selected_phase) is not int or not 0 <= selected_phase <= 2 or
                type(expected_edge_falling) is not bool or
                type(dac_code) is not int or
                not self.amplitude_codes <= dac_code <= 4095-self.amplitude_codes):
            raise FunctionalBemfError('Invalid native Guest comparator routing')
        key = (guest_step, selected_code, selected_phase, expected_edge_falling)
        if key != self._key:
            self._key = key
            self._start_ns = guest_ns
        if guest_ns < self._start_ns:
            raise FunctionalBemfError('Guest virtual time regressed')
        phase_ns = (guest_ns - self._start_ns) % (2*self.crossing_delay_ns)
        crossed = phase_ns >= self.crossing_delay_ns
        # A comparator expected falling edge gets HIGH then LOW.
        # A comparator expected rising edge gets LOW then HIGH.
        sign = (1 if expected_edge_falling else -1) * (-1 if crossed else 1)
        words = [0x10000 | 2048] * 3
        words[selected_phase] = 0x10000 | (dac_code + sign*self.amplitude_codes)
        return BemfVector(guest_ns, guest_step, selected_code, selected_phase,
                          crossed, tuple(words))

    def neutralize(self, write32, read32, base: int):
        """Explicitly remove synthetic BEMF on zero throttle."""
        neutral = (0x10000 | 2048,)*3
        if self._last_words is None or self._last_words == neutral:
            return False
        for phase, word in enumerate(neutral):
            write32(base+4*phase, word)
        for phase, word in enumerate(neutral):
            if read32(base+4*phase) != word:
                raise FunctionalBemfError("SIM_ONLY neutral readback mismatch")
        self._last_words = neutral
        self._key = None
        return True

    def inject(self, vector: BemfVector, write32, read32, base: int):
        """ONLY non-silicon analog three-channel port, never guest CSRs."""
        if not isinstance(vector, BemfVector):
            raise TypeError('Expected validated BemfVector')
        if vector.analog_words == self._last_words:
            return False
        for phase, word in enumerate(vector.analog_words):
            write32(base + 4*phase, word)
        for phase, word in enumerate(vector.analog_words):
            if read32(base + 4*phase) != word:
                raise FunctionalBemfError('SIM_ONLY BEMF input MMIO readback mismatch')
        if vector.crossing_issued and (self._last_words is None or
                                       vector.analog_words != self._last_words):
            self.crossings_issued += 1
        self._last_words = vector.analog_words
        return True
