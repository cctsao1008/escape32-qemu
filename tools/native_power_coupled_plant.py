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

    def __init__(self, parameters, *, initial_electrical_rad=0.0):
        super().__init__(parameters)
        if not math.isfinite(initial_electrical_rad):
            raise ValueError("Explicit finite physical rotor electrical pose required")
        # A rotor at standstill has no BEMF regardless of its angular pose.
        # Electrical pose sets the actual rotor magnetic phase, not a fake
        # voltage edge, external kick, initial RPM, or guest control action.
        self.angle_mech_rad = (
            initial_electrical_rad / self.p.pole_pairs
        ) % (2.0*math.pi)
        self.initial_electrical_rad = initial_electrical_rad
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
            if (len(pairs) != 1 or
                    duties[2*pairs[0][1]+1] < 0.9):
                raise ValueError(
                    "Original six-step source/return conduction window "
                    "not a qualified single-source static sink")
            hi, lo = pairs[0]
            if any(duties[2*i] + duties[2*i+1] > 1.0+1e-9
                   for i in range(3)):
                raise ValueError("Overlapping high/low output in one phase")
            # Two energized windings are in SERIES across the pulsed
            # DC bus. The third floating winding is OPEN; it cannot
            # carry fictitious star-neutral current or torque.
            # The sink has essentially constant conduction in the
            # SIM_ONLY non-PWM_ENABLE topology. min(upper,sink) is an
            # ideal average overlapping conduction fraction, not a
            # switching/diode recovery model.
            fraction = min(duties[2*hi], duties[2*lo+1])
            old = self.sample(gate_enabled=True)
            branch_i = (self.iabc[hi]-self.iabc[lo])*0.5
            branch_v = self.p.vbus_v * fraction
            line_bemf = old.bemf_phase_v[hi]-old.bemf_phase_v[lo]
            branch_i += (
                (branch_v-line_bemf-2*self.p.phase_resistance_ohm*branch_i)
                /(2*self.p.phase_inductance_h) * dt_s)
            self.iabc = [0.0, 0.0, 0.0]
            self.iabc[hi] = branch_i
            self.iabc[lo] = -branch_i
            physical = self.sample(gate_enabled=True)
            omega = self.omega_mech_rad_s
            sign = math.copysign(1.0, omega) if omega else 0.0
            accel = (
                physical.electromagnetic_torque_nm -
                self.p.viscous_friction_nm_per_rad_s*omega -
                self.p.load_torque_nm*sign
            )/self.p.inertia_kg_m2
            new_omega = omega + accel*dt_s
            self.omega_mech_rad_s = new_omega
            self.angle_mech_rad = (
                self.angle_mech_rad+(omega+new_omega)*0.5*dt_s
            ) % (2.0*math.pi)
            if not all(math.isfinite(x) for x in
                       (new_omega, *self.iabc)):
                raise FloatingPointError("Two-terminal BLDC model diverged")
            self.energized_intervals += 1
            self.ever_powered = True
            sample = self.sample(gate_enabled=True)
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
