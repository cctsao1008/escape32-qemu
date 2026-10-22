#!/usr/bin/env python3
"""G13B3B: read-only native MCPWM -> *one-period* VirtualBLDC seed.

Every motor/analog number is an explicitly synthetic SIM_ONLY fixture,
not a real E62 motor, actual board analog net or silicon safety proof.

This step does NOT write any QEMU guest register or motor firmware state.
It does NOT feed the computed BEMF back yet. The next G13B3C must
time-couple actual CMPSS0 -> ECAP1 -> native firmware commutation.
"""
from dataclasses import dataclass
from typing import Callable

from .native_pwm_qualification import observe_original_pwm
from .virtual_bldc import VirtualBLDC, MotorSample
from .virtual_bldc_feedback import AnalogFrontend


@dataclass(frozen=True)
class NativePlantSeed:
    pwm_period_ns: int
    duties: tuple[float, float, float, float, float, float]
    motor: MotorSample
    bemf_voltage_codes: tuple[int, int, int]


def one_native_pwm_period(
    plant: VirtualBLDC,
    frontend: AnalogFrontend,
    read32: Callable[[int], int], *,
    gate_active_level: int,
    timer_hz: int = 100_000_000
) -> NativePlantSeed:
    """Advance one PWM period only if *real native* six output is qualified.

    Does NOT advance QEMU clock or write the simulator's phase inputs;
    it simply proves that a native PWM image is a usable physical-drive
    input to the independently existing VirtualBLDC model. A single
    host-side integration is NOT commutation, zero crossing or closed loop.
    """
    if not isinstance(timer_hz, int) or timer_hz <= 0:
        raise ValueError("SIM_ONLY MCPWM4 timer rate must be explicit")
    qualification = observe_original_pwm(
        read32, gate_active_level=gate_active_level)
    if not qualification.acceptable_for_plant:
        raise ValueError(
            "Guest-owned PWM not qualified for plant: " +
            qualification.reason)
    period = qualification.period_ticks
    if period * 1_000_000_000 % timer_hz:
        raise ValueError("Guest PWM period not representable as whole ns")
    period_ns = (period * 1_000_000_000) // timer_hz
    if period_ns <= 0:
        raise ValueError("Native PWM physical time must advance")
    duties = qualification.six_duties
    assert duties is not None  # established by observation qualification
    sample = plant.advance(duties, period_ns / 1_000_000_000,
                           gate_enabled=True)
    codes = frontend.words(sample)
    return NativePlantSeed(
        pwm_period_ns=period_ns,
        duties=duties, motor=sample,
        bemf_voltage_codes=codes
    )
