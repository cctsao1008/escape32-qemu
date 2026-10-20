#!/usr/bin/env python3
"""ESC-SIM host-side six-output BLDC motor equations (G9b groundwork).

This module NEVER drives ESCape32 firmware variables or manufactures PWM.
It consumes six actual MCPWM4 output duty measurements. It does not yet
inject CMPSS0/ECAP1 BEMF events back into QEMU. That hardware link must
be independently implemented and tested before claiming closed-loop SITL.
All parameters are explicit: no undocumented TI motor defaults.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Sequence

OBS_BASE = 0x5FFE1000

# SDK hw_pinmap.h six-route map from AM13E board_motor_output_reference.c.
# This is not sufficient for electrical board qualification; it merely
# prevents the host model from assuming the six pads/gate are active.
MCPWM4_ROUTES = ((8, 6), (21, 5), (24, 4),
                 (2, 6), (10, 4), (25, 12))
GPIO1_BASE = 0x400F2000
PINCM_BASE = 0x400CC000
GATE_EN = 1 << 13


def gate_and_pads_connected(
    read32: Callable[[int], int], *, gate_active_level: int
) -> bool:
    """Check native GPIO PB13 + PWM pad mux; polarity MUST be explicit.

    Does not validate driver reset/OC, gate propagation delay or hardware
    safety. When false, the host must not apply drive voltage.
    """
    if gate_active_level not in (0, 1):
        raise ValueError("Explicit physical/simulation gate polarity required")
    # PB13 gate-drive needs both GPIO1 power and its actual pad mux.
    # DOE/DOUT alone do NOT prove a physical output connection.
    if (read32(PINCM_BASE + 4 * 45) & 0xBF) != 0x81:
        return False
    if not (read32(GPIO1_BASE + 0x800) & 1):
        return False
    if not (read32(GPIO1_BASE + 0x12C0) & GATE_EN):
        return False
    if bool(read32(GPIO1_BASE + 0x1280) & GATE_EN) != bool(gate_active_level):
        return False
    for pin, mux in MCPWM4_ROUTES:
        cfg = read32(PINCM_BASE + 4 * pin)
        if (cfg & 0x80) == 0 or (cfg & 0x3F) != mux:
            return False
    return True

TWO_PI = 2.0 * math.pi


@dataclass(frozen=True)
class MotorParameters:
    vbus_v: float
    phase_resistance_ohm: float
    phase_inductance_h: float
    bemf_constant_v_per_rad_s: float
    torque_constant_nm_per_a: float
    inertia_kg_m2: float
    viscous_friction_nm_per_rad_s: float
    load_torque_nm: float
    pole_pairs: int

    def __post_init__(self) -> None:
        strictly_positive = (
            "vbus_v", "phase_resistance_ohm", "phase_inductance_h",
            "bemf_constant_v_per_rad_s", "torque_constant_nm_per_a",
            "inertia_kg_m2",
        )
        for field in strictly_positive:
            value = getattr(self, field)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{field} must be positive and finite")
        for field in ("viscous_friction_nm_per_rad_s", "load_torque_nm"):
            value = getattr(self, field)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{field} must be nonnegative and finite")
        if not isinstance(self.pole_pairs, int) or self.pole_pairs <= 0:
            raise ValueError("pole_pairs must be a positive integer")


@dataclass(frozen=True)
class PWMObservation:
    period_ticks: int
    high_ticks: tuple[int, int, int, int, int, int]
    running: bool
    valid_mask: int

    @classmethod
    def from_qemu(cls, read32: Callable[[int], int]) -> PWMObservation:
        status = read32(OBS_BASE)
        period = read32(OBS_BASE + 8)
        valid = read32(OBS_BASE + 0x14)
        counts = tuple(read32(OBS_BASE + 0x18 + i*4) for i in range(6))
        running = bool(status & 1)
        if not running or not (status & 8) or valid != 0x3F:
            raise ValueError(
                "MCPWM4 outputs not running/valid: "
                f"status=0x{status:X} valid=0x{valid:X}; "
                "do not inject BEMF from invalid duty")
        if period <= 0 or any(x < 0 or x > period for x in counts):
            raise ValueError("Invalid MCPWM4 high-tick counts/period")
        return cls(period, counts, running, valid)

    @property
    def six_duties(self) -> tuple[float, float, float, float, float, float]:
        p = float(self.period_ticks)
        return tuple(x/p for x in self.high_ticks)


@dataclass(frozen=True)
class MotorSample:
    mechanical_rpm: float
    electrical_rad: float
    phase_currents_a: tuple[float, float, float]
    bemf_phase_v: tuple[float, float, float]
    electromagnetic_torque_nm: float
    drive_enabled: bool


class VirtualBLDC:
    """Simplified star-connected balanced three-phase R-L-BEMF dynamics.

    Optional gate=False represents a disconnected bridge, not a
    fictitious 0% PWM command to a live power stage. At rest with
    gate=False, speed and BEMF remain exactly zero.

    This is a deliberately simplified ideal-switching motor model:
    no winding saturation, cogging, commutator inductance or MOSFET
    loss. It is not a substitute for power-stage/Trip qualification.
    """

    def __init__(self, p: MotorParameters):
        self.p = p
        self.omega_mech_rad_s = 0.0
        self.angle_mech_rad = 0.0
        self.iabc = [0.0, 0.0, 0.0]

    def sample(self, gate_enabled: bool = False) -> MotorSample:
        theta = self.p.pole_pairs * self.angle_mech_rad
        phases = [math.sin(theta + delta)
                  for delta in (0.0, -TWO_PI/3, TWO_PI/3)]
        bemf = tuple(
            self.p.bemf_constant_v_per_rad_s *
            self.p.pole_pairs * self.omega_mech_rad_s * x
            for x in phases)
        torque = self.p.torque_constant_nm_per_a * sum(
            current * basis
            for current, basis in zip(self.iabc, phases))
        return MotorSample(
            mechanical_rpm=self.omega_mech_rad_s*60.0/TWO_PI,
            electrical_rad=theta % TWO_PI,
            phase_currents_a=tuple(self.iabc),
            bemf_phase_v=bemf,
            electromagnetic_torque_nm=torque,
            drive_enabled=gate_enabled,
        )

    def advance(
        self, duties: Sequence[float], dt_s: float, *,
        gate_enabled: bool
    ) -> MotorSample:
        if len(duties) != 6:
            raise ValueError("Expected six measured output duties")
        if not math.isfinite(dt_s) or dt_s <= 0:
            raise ValueError("dt_s must be positive and finite")
        if any(not math.isfinite(x) or x < 0.0 or x > 1.0
               for x in duties):
            raise ValueError("Each output duty must be in [0, 1]")
        for phase in range(3):
            if duties[phase*2] + duties[phase*2+1] > 1.0+1e-9:
                raise ValueError(
                    f"Phase {phase}: overlapping high/low average; "
                    "unsafe or incorrectly modeled switching")

        # Switching-frame averaged line voltages, not phase-to-neutral
        # voltage measurement. Floating phases have zero drive.
        voltage = (
            [self.p.vbus_v * 0.5 *
             (duties[2*i] - duties[2*i+1]) for i in range(3)]
            if gate_enabled else [0.0, 0.0, 0.0]
        )
        old = self.sample(gate_enabled=gate_enabled)
        # Floating star neutral is the arithmetic mean of phase
        # terminals in this reduced-order balanced model.
        vneutral = sum(voltage)/3.0
        en = sum(old.bemf_phase_v)/3.0
        mean_i = sum(self.iabc)/3.0
        for i in range(3):
            vphase = voltage[i]-vneutral
            bemf = old.bemf_phase_v[i]-en
            derivative = (
                vphase-bemf-self.p.phase_resistance_ohm *
                (self.iabc[i]-mean_i)
            )/self.p.phase_inductance_h
            self.iabc[i] += derivative * dt_s
        # Explicitly enforce star connection (Ia+Ib+Ic=0).
        current_mean = sum(self.iabc)/3.0
        self.iabc = [x-current_mean for x in self.iabc]
        current = self.sample(gate_enabled=gate_enabled)
        sign = math.copysign(1.0, self.omega_mech_rad_s) \
            if self.omega_mech_rad_s else 0.0
        acceleration = (
            current.electromagnetic_torque_nm -
            self.p.viscous_friction_nm_per_rad_s *
            self.omega_mech_rad_s -
            self.p.load_torque_nm*sign
        )/self.p.inertia_kg_m2
        self.omega_mech_rad_s += acceleration*dt_s
        self.angle_mech_rad = (
            self.angle_mech_rad + self.omega_mech_rad_s*dt_s
        ) % TWO_PI
        if not all(math.isfinite(x)
                   for x in (self.omega_mech_rad_s, *self.iabc)):
            raise FloatingPointError(
                "Motor integration diverged; reduce dt_s / verify parameters")
        return self.sample(gate_enabled=gate_enabled)


def update_from_mcpwm(
    plant: VirtualBLDC, read32: Callable[[int], int], *,
    gate_enabled: bool, timer_hz: int = 100_000_000
) -> MotorSample:
    """Use measured six HIGH-tick counts, never firmware throttle."""
    obs = PWMObservation.from_qemu(read32)
    if timer_hz <= 0:
        raise ValueError("MCPWM actual timer frequency must be positive")
    tbctl = read32(0x40014010)
    divider = (tbctl >> 2) & 15
    if divider > 7:
        raise ValueError("Unsupported MCPWM4 time-base divider")
    return plant.advance(
        obs.six_duties, obs.period_ticks * (1 << divider) / timer_hz,
        gate_enabled=gate_enabled,
    )
