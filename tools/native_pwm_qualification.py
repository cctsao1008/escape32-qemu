#!/usr/bin/env python3
"""G13B3A: qualify *guest-owned* six-channel native MCPWM output.

Read-only diagnostic bridge between the original Firmware's positive
G13B2E Gate/Pad state and G13A host VirtualBLDC. NEVER infer duty from
DShot/throt, force AQ/Compare, fake BEMF, or bypass hardware Trip.

All numeric electrical settings here are strictly SIM_ONLY.
"""
from dataclasses import dataclass, asdict
from typing import Callable

from .virtual_bldc import (
    OBS_BASE, PWMObservation, gate_and_pads_connected,
    MCPWM4_ROUTES, PINCM_BASE, GPIO1_BASE, GATE_EN,
)

MCPWM4 = 0x40014000
SYSCTL_PERCLKCR = 0x400B048C
SYSCTL_PWREN = 0x400B0424


@dataclass(frozen=True)
class NativeOutputEvidence:
    gate_and_pads: bool
    pwm_powered: bool
    pwm_tbclk_enabled: bool
    physical_ost2: bool
    physical_ost3: bool
    pwm_status: int
    valid_mask: int
    period_ticks: int
    six_high_ticks: tuple[int, int, int, int, int, int]
    six_duties: tuple[float, float, float, float, float, float] | None
    native_pwm_valid: bool
    nonzero_phase_voltage_command: bool
    acceptable_for_plant: bool
    reason: str

    def to_dict(self):
        return asdict(self)


def observe_original_pwm(
    read32: Callable[[int], int], *, gate_active_level: int = 1
) -> NativeOutputEvidence:
    """Assess *read-only* original guest MCPWM output at one HALT instant.

    A single instantaneous image proves neither repeated commutation nor
    physical motor motion. It is a prerequisite to dynamic plant coupling.
    A genuine already-latched OST2/3 inhibits application of motor voltage,
    even if gate/pads remain enabled and AQ registers carry nonzero duties.
    """
    if gate_active_level not in (0, 1):
        raise ValueError("Native board profile must explicitly select polarity")
    status = read32(OBS_BASE)
    valid = read32(OBS_BASE + 0x14)
    period = read32(OBS_BASE + 8)
    high = tuple(read32(OBS_BASE + 0x18 + 4 * i) for i in range(6))
    tz = read32(MCPWM4 + 0xb0)
    ost2, ost3 = bool(tz & 0x20000), bool(tz & 0x40000)
    pwren = read32(SYSCTL_PWREN)
    tbclk = read32(SYSCTL_PERCLKCR)
    gate = gate_and_pads_connected(read32, gate_active_level=gate_active_level)
    powered = (pwren & 0x200) != 0
    clk = (tbclk & 1) != 0
    obs = None
    invalid = ""
    try:
        obs = PWMObservation.from_qemu(read32)
    except ValueError as exc:
        invalid = str(exc)
    duties = obs.six_duties if obs else None
    # All six outputs may be valid and zero; no electric power is
    # demonstrated without an observed nonzero differential command.
    phase_drive = bool(obs and any(
        obs.high_ticks[2*i] != obs.high_ticks[2*i+1]
        for i in range(3)
    ))
    reasons = []
    if not gate:
        reasons.append("PB13 gate or one of six PINCM routes not qualified")
    if not powered:
        reasons.append("MCPWM4 is not powered")
    if not clk:
        reasons.append("MCPWM4 TBCLKSYNC is off")
    if ost2 or ost3:
        reasons.append("hardware Trip OST2/OST3 is latched")
    if not obs:
        reasons.append("invalid original six-channel PWM observer: " + invalid)
    if not phase_drive:
        reasons.append("no native nonzero differential phase command yet")
    return NativeOutputEvidence(
        gate_and_pads=gate, pwm_powered=powered,
        pwm_tbclk_enabled=clk, physical_ost2=ost2,
        physical_ost3=ost3, pwm_status=status,
        valid_mask=valid, period_ticks=period,
        six_high_ticks=high, six_duties=duties,
        native_pwm_valid=obs is not None,
        nonzero_phase_voltage_command=phase_drive,
        acceptable_for_plant=not reasons,
        reason="; ".join(reasons) if reasons else
               "all six original PWM outputs and physical gate/trip qualified",
    )
