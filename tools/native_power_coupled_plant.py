#!/usr/bin/env python3
"""Open-star ideal coasting vs genuinely powered three-phase VirtualBLDC.

The existing G13A model can falsely accelerate with one sink only; that
is deliberately NOT used for G13B3L closed-loop qualification. No
fabricated rotor initial RPM/BEMF, guest writes or forced captures.
"""
import math
from .virtual_bldc import VirtualBLDC
from .native_power_path_qualification import qualify_cross_phase_bridge


class NativePowerCoupledBLDC(VirtualBLDC):
    """Advance real simplified R-L motor only when a two-terminal path exists.

    In open-bridge mode ignore static sink PWM; rotor coasts with physical
    viscous friction and external load; floating winding currents are zero
    in this idealized model. No diode conduction/cogging/saturation modeled.
    """

    def __init__(self, parameters):
        super().__init__(parameters)
        self.energized_intervals = 0
        self.coasting_intervals = 0
        self.max_measured_rpm = 0.0
        self.ever_powered = False

    def advance(self, duties, dt_s, *, gate_enabled):
        if len(duties) != 6 or not math.isfinite(dt_s) or dt_s <= 0:
            raise ValueError("Six measured duties and positive finite duration needed")
        if any(not math.isfinite(x) or x < 0 or x > 1 for x in duties):
            raise ValueError("Measured duty out of range")
        pairs = [(i,j) for i in range(3) for j in range(3)
                 if i != j and duties[2*i] > 0 and duties[2*j+1] > 0]
        energized = bool(gate_enabled and pairs)
        if energized:
            self.energized_intervals += 1
            self.ever_powered = True
            sample = super().advance(duties, dt_s, gate_enabled=True)
        else:
            self.coasting_intervals += 1
            # Physically open winding: no invented bus-to-neutral voltage.
            self.iabc = [0.0, 0.0, 0.0]
            old_omega = self.omega_mech_rad_s
            if old_omega:
                decel = ((self.p.viscous_friction_nm_per_rad_s * abs(old_omega)
                          + self.p.load_torque_nm) / self.p.inertia_kg_m2) * dt_s
                next_omega = math.copysign(max(0.0, abs(old_omega) - decel),
                                            old_omega)
                self.omega_mech_rad_s = next_omega
                self.angle_mech_rad = (
                    self.angle_mech_rad + (old_omega + next_omega) * 0.5 * dt_s
                ) % (2.0*math.pi)
            sample = self.sample(gate_enabled=False)
        self.max_measured_rpm = max(self.max_measured_rpm,
                                    abs(sample.mechanical_rpm))
        return sample
