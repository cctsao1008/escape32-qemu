#!/usr/bin/env python3
"""G13A: explicit, QTest-only measured-PWM -> BLDC -> comparator fixture.

This bridge does NOT modify the native ESCape32 firmware. It cannot
enable any motor hardware. QTest must independently configure the exact
powered MCPWM4 / PB13 gate / six PINCM routes / CMPSS0 / ECAP1 registers.
Only the *read-only* MCPWM4 six-output observer supplies phase drives.

This is a bounded, fixture-calibrated BEMF-only comparator input. Without
a selected motor and board's analog divider/offset/power-stage details,
it is NOT a qualified phase-terminal-voltage or closed-loop ESC model.
"""
from dataclasses import dataclass
import math
from typing import Callable

from .virtual_bldc import (
    OBS_BASE, MotorSample, PWMObservation, VirtualBLDC,
    gate_and_pads_connected
)

SIM_BEMF_INPUT = 0x5FFE2000  # NON-SILICON QEMU fixture
SYS_POWER = 0x400AF000 + 0x1424
SYS_HP_MUX = 0x400AF000 + 0x1444
MCPWM_TBCTL = 0x40014010
CMPSS0 = 0x40460000
ECAP1 = 0x40441000


@dataclass(frozen=True)
class AnalogFrontend:
    """All analog constants are TEST FIXTURE parameters, not TI defaults."""

    reference_v: float
    zero_bemf_bias_v: float
    input_gain_v_per_bemf_v: float

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (
                self.reference_v, self.zero_bemf_bias_v,
                self.input_gain_v_per_bemf_v)):
            raise ValueError("Analog frontend numbers must be finite")
        if (self.reference_v <= 0 or not (
                0 < self.zero_bemf_bias_v < self.reference_v) or
                self.input_gain_v_per_bemf_v <= 0):
            raise ValueError("Analog frontend needs Vref, bias, positive gain")

    def code(self, bemf_v: float) -> int:
        if not math.isfinite(bemf_v):
            raise ValueError("Nonfinite motor BEMF cannot drive a comparator")
        v = self.zero_bemf_bias_v + self.input_gain_v_per_bemf_v * bemf_v
        # Do not quietly clip: saturation changes zero crossing semantics.
        if not 0 <= v <= self.reference_v:
            raise ValueError(
                "BEMF analog fixture saturated; choose grounded frontend "
                "parameters, not a hidden clamp")
        return max(0, min(4095, round(4095 * v / self.reference_v)))

    def words(self, state: MotorSample) -> tuple[int, int, int]:
        if len(state.bemf_phase_v) != 3:
            raise ValueError("Expected three BEMF phase values")
        return tuple(0x10000 | self.code(v) for v in state.bemf_phase_v)


@dataclass(frozen=True)
class BridgeResult:
    original_pwm_duties: tuple[float, float, float, float, float, float]
    hold_periods: int
    elapsed_virtual_ns: int
    motor: MotorSample
    comparator_words: tuple[int, int, int]


def bridge_pwm_to_bemf(
    plant: VirtualBLDC,
    analog: AnalogFrontend,
    read32: Callable[[int], int],
    write32: Callable[[int, int], None],
    advance_virtual_ns: Callable[[int], None],
    *,
    gate_active_level: int,
    pwm_timer_hz: int,
    hold_periods: int,
    input_phase: int = 0
) -> BridgeResult:
    """Use only observed six real QEMU PWM outputs and qualified pad state.

    Entire batch assumes the QTest *fixture* holds the same PWM image.
    The callback advances QEMU's virtual timer by exactly the integrated
    motor time *before* injecting the derived BEMF words. It is not a
    native firmware closed loop: QTest, not the ESCape32 guest, programs
    the power / PWM / comparator / ECAP device registers.
    """
    if (not isinstance(hold_periods, int) or
            not 1 <= hold_periods <= 10000 or
            not isinstance(pwm_timer_hz, int) or pwm_timer_hz <= 0):
        raise ValueError("Explicit bounded PWM periods and clock required")
    if not 0 <= input_phase <= 2:
        raise ValueError("Selected CMPSS phase must be U/V/W")
    if not gate_and_pads_connected(read32, gate_active_level=gate_active_level):
        raise ValueError("PB13 gate or six physical PWM pad routes not qualified")
    obs = PWMObservation.from_qemu(read32)
    if (read32(SYS_POWER) & 0x410) != 0x410:
        raise ValueError("ECAP1/CMPSS0 must be powered before BEMF transfer")
    if (read32(ECAP1 + 0x24) != 45 or
            (read32(SYS_HP_MUX) & 7) != input_phase or
            not (read32(CMPSS0) & 0x8000)):
        raise ValueError("Native CMPSS0 high / ECAP Input45 route not enabled")
    tbctl = read32(MCPWM_TBCTL)
    divider = (tbctl >> 2) & 15
    if divider > 7:
        raise ValueError("Unsupported MCPWM4 clock divider")
    tick_count = obs.period_ticks * (1 << divider)
    numerator = tick_count * 1_000_000_000
    if numerator % pwm_timer_hz:
        raise ValueError("PWM period cannot be represented in whole ns")
    period_ns = numerator // pwm_timer_hz
    if period_ns <= 0:
        raise ValueError("PWM period must advance QEMU virtual clock")
    dt = period_ns * 1e-9
    duties = obs.six_duties
    for _ in range(hold_periods):
        sample = plant.advance(duties, dt, gate_enabled=True)
    words = analog.words(sample)
    # Requalify after integration and before any simulator stimulus write.
    if not gate_and_pads_connected(read32, gate_active_level=gate_active_level):
        raise ValueError("Gate/pad qualification lost; abort, do not inject")
    if PWMObservation.from_qemu(read32) != obs:
        raise ValueError("PWM outputs changed during held-image integration")
    total_ns = period_ns * hold_periods
    advance_virtual_ns(total_ns)
    for phase, word in enumerate(words):
        write32(SIM_BEMF_INPUT + 4 * phase, word)
    return BridgeResult(duties, hold_periods, total_ns, sample, words)
