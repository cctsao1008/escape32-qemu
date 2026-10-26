"""Independent fixed-frequency three-phase functional analog stimulus.

NOT motor physics. No Guest MUX/step/selected_code/polarity/DAC decision
affects waveform phase: U/V/W share one external electrical angle clock.
A virtual motor neutral *reference code* is an internal waveform parameter,
NOT an AM13E external VN input, Guest DAC write, or ADC-channel claim.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

CONFIG_PATH = (Path(__file__).resolve().parents[1] /
               "configs/e62-functional-bemf.json")
SIM_ONLY_PHASE_VALID = 0x10000


@dataclass(frozen=True)
class ThreePhaseConfig:
    electrical_hz: float
    initial_degrees: float
    center_code: int
    amplitude_codes: int
    sample_wfi_interval: int


def load_three_phase_config(path=None) -> ThreePhaseConfig:
    location = Path(path) if path is not None else CONFIG_PATH
    d = json.loads(location.read_text(encoding="utf-8"))
    if (not isinstance(d, dict) or d.get("schema") !=
            "e62.functional-bemf.v1" or
            d.get("mode") != "INDEPENDENT_THREE_PHASE_FIXED_HZ" or
            set(d) != {"schema", "mode", "electrical_hz",
                       "initial_electrical_degrees", "center_code",
                       "amplitude_codes", "sample_wfi_interval"}):
        raise ValueError("Unsupported independent three-phase BEMF config")
    hz = d["electrical_hz"]
    deg = d["initial_electrical_degrees"]
    mid = d["center_code"]
    amp = d["amplitude_codes"]
    interval = d["sample_wfi_interval"]
    if (type(hz) not in (int, float) or not math.isfinite(hz) or
            not 1 <= hz <= 2000 or
            type(deg) not in (int, float) or not math.isfinite(deg) or
            not -360 <= deg <= 360 or
            type(mid) is not int or not 512 <= mid <= 3583 or
            type(amp) is not int or not 1 <= amp <= 512 or
            mid-amp < 0 or mid+amp > 4095 or
            type(interval) is not int or not 1 <= interval <= 20):
        raise ValueError("Invalid independent three-phase BEMF parameters")
    return ThreePhaseConfig(float(hz), float(deg), mid, amp, interval)


@dataclass(frozen=True)
class ThreePhaseSample:
    guest_elapsed_ns: int
    electrical_degrees: float
    analog_words: tuple[int, int, int]


class IndependentThreePhaseBemf:
    def __init__(self, config: ThreePhaseConfig):
        if not isinstance(config, ThreePhaseConfig):
            raise TypeError("ThreePhaseConfig required")
        self.config = config
        self.previous_words = None
        self.crossings_issued = 0
        self.injected_samples = 0
        self.last_guest_ns = None

    def evaluate(self, *, guest_ns: int) -> ThreePhaseSample:
        if type(guest_ns) is not int or guest_ns < 0:
            raise ValueError("Invalid original Guest virtual time")
        c = self.config
        theta = ((c.initial_degrees +
                  (guest_ns / 1_000_000_000) * c.electrical_hz * 360)
                 % 360.0)
        angles = (theta, theta - 120.0, theta + 120.0)
        codes = tuple(c.center_code + round(
            c.amplitude_codes * math.sin(math.radians(a))) for a in angles)
        if not all(0 <= x <= 4095 for x in codes):
            raise ValueError("Three-phase ADC-compatible codes out of range")
        return ThreePhaseSample(guest_ns, theta,
                                tuple(SIM_ONLY_PHASE_VALID | x for x in codes))

    def inject(self, sample: ThreePhaseSample, write32, read32, base: int):
        """Write only the three SIM_ONLY analog input words, never Guest CSR."""
        if not isinstance(sample, ThreePhaseSample):
            raise TypeError("ThreePhaseSample required")
        if (self.last_guest_ns is not None and
                sample.guest_elapsed_ns < self.last_guest_ns):
            raise ValueError("Original Guest time regressed")
        words = sample.analog_words
        if self.previous_words is not None:
            center = self.config.center_code
            for a, b in zip(self.previous_words, words):
                if ((a & 0xfff) > center) != ((b & 0xfff) > center):
                    self.crossings_issued += 1
        if words != self.previous_words:
            for phase, word in enumerate(words):
                write32(base + 4*phase, word)
            for phase, word in enumerate(words):
                if read32(base + 4*phase) != word:
                    raise AssertionError("Independent SIM_ONLY BEMF readback mismatch")
        self.previous_words = words
        self.last_guest_ns = sample.guest_elapsed_ns
        self.injected_samples += 1
        return True

    def neutralize(self, write32, read32, base: int):
        neutral = tuple(SIM_ONLY_PHASE_VALID |
                        self.config.center_code for _ in range(3))
        if self.previous_words != neutral:
            for phase, word in enumerate(neutral):
                write32(base + 4*phase, word)
            for phase, word in enumerate(neutral):
                if read32(base + 4*phase) != word:
                    raise AssertionError("Independent analog neutral mismatch")
        self.previous_words = neutral
        return True
