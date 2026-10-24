#!/usr/bin/env python3
"""Isolated host-only current-continuous star BLDC with explicit ideal diodes.

Inputs are instantaneous externally specified H/L/Z MOS-leg states, NOT
six-PWM high-tick duty averages. At switch changes current is NEVER
projected/reset. Per-substep constrained back-Euler enforces star KCL:
H=Vbus, L=0, Z may be OPEN (i=0), LOW_DIODE (i>=0, V=-Vf),
or HIGH_DIODE (i<=0, V=Vbus+Vf). Endpoint active-set conduction is
idealized; real freewheel, deadtime and edge waveforms are NOT qualified.
No QEMU, Guest, ESCape32 control, or BEMF-injection linkage.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
import math

from .virtual_bldc import MotorParameters, VirtualBLDC


@dataclass(frozen=True)
class LegTopology:
    """Instantaneous U/V/W MOS connections: H high, L low, Z both OFF."""
    legs: tuple[str, str, str]

    def __post_init__(self):
        if (not isinstance(self.legs, tuple) or len(self.legs) != 3 or
                any(type(s) is not str or s not in ("H", "L", "Z")
                    for s in self.legs)):
            raise ValueError(
                "Three explicit H/L/Z instantaneous leg states required")


@dataclass(frozen=True)
class ConductionState:
    states: tuple[str, str, str]
    terminal_voltages_v: tuple[float, float, float]
    phase_currents_a: tuple[float, float, float]
    star_neutral_v: float


class CurrentContinuousBLDC(VirtualBLDC):
    """Opt-in host experiment, NEVER a drop-in native SITL motor."""

    def __init__(self, parameters: MotorParameters, *,
                 initial_electrical_rad: float = 0.0,
                 diode_forward_v: float = 0.7,
                 max_electrical_step_rad: float = 0.35):
        super().__init__(parameters)
        if not math.isfinite(initial_electrical_rad):
            raise ValueError("Finite initial electrical rotor pose required")
        if not math.isfinite(diode_forward_v) or diode_forward_v < 0:
            raise ValueError("Nonnegative, finite explicit diode drop required")
        if (not math.isfinite(max_electrical_step_rad) or
                not 0 < max_electrical_step_rad <= math.pi/2):
            raise ValueError("Finite bounded electrical timestep guard required")
        if not math.isclose(
                parameters.torque_constant_nm_per_a,
                parameters.bemf_constant_v_per_rad_s * parameters.pole_pairs,
                rel_tol=1e-10, abs_tol=0):
            raise ValueError(
                "Current-continuous physical audit requires reciprocal Ke/Kt")
        self.angle_mech_rad = (
            initial_electrical_rad / parameters.pole_pairs) % (2*math.pi)
        self.diode_forward_v = float(diode_forward_v)
        self.max_electrical_step_rad = float(max_electrical_step_rad)
        self.topology = LegTopology(("Z", "Z", "Z"))
        self.last_conduction: ConductionState | None = None
        self.topology_changes = 0
        self.first_topology_events: list[dict] = []
        self.integrated_intervals = 0
        self.diode_conduction_intervals = 0
        self.bus_input_j = 0.0
        self.copper_loss_j = 0.0
        self.diode_loss_j = 0.0
        self.friction_loss_j = 0.0
        self.load_loss_j = 0.0
        self.bemf_conversion_j = 0.0
        self.shaft_conversion_j = 0.0
        self.magnetic_delta_j = 0.0
        self.kinetic_delta_j = 0.0
        self.raw_residual_j = 0.0
        self.abs_residual_j = 0.0
        self.max_step_residual_j = 0.0
        self.backward_euler_current_numerical_loss_j = 0.0
        self.forced_current_projection_impulse_j = 0.0

    def set_switches(self, topology: LegTopology):
        """Switches instantaneously without modifying the old winding currents."""
        if not isinstance(topology, LegTopology):
            raise TypeError(
                "Explicit LegTopology required; duty averages forbidden")
        before = tuple(self.iabc)
        old_energy = self.magnetic_energy_j
        old_topology = self.topology
        self.topology = topology
        if topology != old_topology:
            self.topology_changes += 1
            if len(self.first_topology_events) < 16:
                self.first_topology_events.append({
                    "old_switches": list(old_topology.legs),
                    "new_switches": list(topology.legs),
                    "phase_currents_at_switch_a": list(before),
                    "magnetic_energy_at_switch_j": old_energy,
                    "artificial_current_projection_energy_j": 0.0,
                    "physical_commutation_transient_fully_resolved": False,
                })
        if tuple(self.iabc) != before or self.magnetic_energy_j != old_energy:
            raise AssertionError("Switch change modified current or energy")

    @property
    def magnetic_energy_j(self):
        return 0.5*self.p.phase_inductance_h*sum(i*i for i in self.iabc)

    def _solve_diodes(self, old_i, old_e, dt):
        """Constrained ideal-diode endpoint active set, NOT edge-resolved."""
        p = self.p
        h = dt/p.phase_inductance_h
        inv_den = 1/(1+h*p.phase_resistance_ohm)
        low_v, high_v = -self.diode_forward_v, p.vbus_v+self.diode_forward_v
        z_idxs = [k for k, leg in enumerate(self.topology.legs) if leg == "Z"]
        for states in product(("OPEN", "LOW_DIODE", "HIGH_DIODE"),
                              repeat=len(z_idxs)):
            modes = list(self.topology.legs)
            for j, state in zip(z_idxs, states):
                modes[j] = state
            v = [None]*3
            fixed = []
            for j, mode in enumerate(modes):
                if mode == "H":
                    v[j] = p.vbus_v
                elif mode == "L":
                    v[j] = 0.0
                elif mode == "LOW_DIODE":
                    v[j] = low_v
                elif mode == "HIGH_DIODE":
                    v[j] = high_v
                if v[j] is not None:
                    fixed.append(j)
            if fixed:
                nu = sum(
                    old_i[j]/h+v[j]-old_e[j] for j in fixed)/len(fixed)
            else:
                offsets = [old_e[j]-old_i[j]/h for j in range(3)]
                minimum = max(low_v-x for x in offsets)
                maximum = min(high_v-x for x in offsets)
                if minimum > maximum + 1e-10:
                    continue
                nu = (minimum+maximum)/2
            curr = []
            valid = True
            for j, mode in enumerate(modes):
                if mode == "OPEN":
                    v[j] = nu+old_e[j]-old_i[j]/h
                    if not low_v-1e-8 <= v[j] <= high_v+1e-8:
                        valid = False
                    curr.append(0.0)
                else:
                    new_i = (
                        old_i[j]+h*(v[j]-nu-old_e[j]))*inv_den
                    if (mode == "LOW_DIODE" and new_i < -1e-9 or
                            mode == "HIGH_DIODE" and new_i > 1e-9):
                        valid = False
                    curr.append(new_i)
            if not valid:
                continue
            if abs(sum(curr)) > 1e-8*max(1.0, *(abs(i) for i in curr)):
                continue
            if not all(math.isfinite(x) for x in (nu, *curr, *v)):
                continue
            return ConductionState(
                tuple(modes), tuple(v), tuple(curr), nu)
        raise ValueError(
            "No consistent explicit ideal-diode conduction solution; "
            "reduce timestep or inspect specified leg topology")

    def advance(self, dt_s: float):
        """Advance only the declared instantaneous leg state over dt."""
        if (not isinstance(dt_s, (int, float)) or
                not math.isfinite(dt_s) or dt_s <= 0):
            raise ValueError("Finite positive integration timestep required")
        p = self.p
        old_omega = self.omega_mech_rad_s
        if abs(p.pole_pairs*old_omega*dt_s) > self.max_electrical_step_rad:
            raise ValueError("Electrical rotor advance exceeds explicit step guard")
        old_i = tuple(self.iabc)
        old_sample = self.sample(
            gate_enabled=any(s != "Z" for s in self.topology.legs))
        solution = self._solve_diodes(
            old_i, old_sample.bemf_phase_v, dt_s)
        new_i = solution.phase_currents_a
        theta = p.pole_pairs*self.angle_mech_rad
        basis = tuple(math.sin(theta+d) for d in (
            0.0, -2*math.pi/3, 2*math.pi/3))
        torque = p.torque_constant_nm_per_a*sum(
            i*b for i,b in zip(new_i,basis))
        undamped = (old_omega+dt_s*torque/p.inertia_kg_m2)/(
            1+dt_s*p.viscous_friction_nm_per_rad_s/p.inertia_kg_m2)
        coulomb = dt_s*p.load_torque_nm/(
            p.inertia_kg_m2+dt_s*p.viscous_friction_nm_per_rad_s)
        if abs(undamped) <= coulomb:
            new_omega = 0.0
        else:
            new_omega = undamped-math.copysign(coulomb, undamped)
        if abs(p.pole_pairs*new_omega*dt_s) > self.max_electrical_step_rad:
            raise ValueError("Accelerated rotor exceeds electrical step guard")
        new_angle = (self.angle_mech_rad+(
            old_omega+new_omega)*dt_s/2) % (2*math.pi)
        if not all(math.isfinite(x) for x in (*new_i, new_omega, new_angle)):
            raise FloatingPointError("Current-continuous host model diverged")
        bus_i = sum(i for i, mode in zip(new_i, solution.states)
                    if mode in ("H", "HIGH_DIODE"))
        diode_i = sum(abs(i) for i, mode in zip(new_i, solution.states)
                      if mode in ("LOW_DIODE", "HIGH_DIODE"))
        ein = p.vbus_v*bus_i*dt_s
        ediode = self.diode_forward_v*diode_i*dt_s
        ecopper = p.phase_resistance_ohm*sum(i*i for i in new_i)*dt_s
        ebemf = sum(e*i for e,i in zip(
            old_sample.bemf_phase_v,new_i))*dt_s
        emag = 0.5*p.phase_inductance_h*sum(
            i*i-old*old for i,old in zip(new_i,old_i))
        ekin = 0.5*p.inertia_kg_m2*(
            new_omega**2-old_omega**2)
        efriction = p.viscous_friction_nm_per_rad_s*new_omega**2*dt_s
        eload = p.load_torque_nm*abs(new_omega)*dt_s
        eshaft = torque*new_omega*dt_s
        raw = ein-ediode-ecopper-emag-ekin-efriction-eload
        euler_current_loss = 0.5*p.phase_inductance_h*sum(
            (i-old)**2 for i,old in zip(new_i,old_i))
        values = (ein, ediode, ecopper, ebemf, emag, ekin,
                  efriction, eload, eshaft, raw, euler_current_loss)
        if not all(math.isfinite(x) for x in values) or (
                ecopper < 0 or ediode < 0 or efriction < 0 or eload < 0):
            raise FloatingPointError(
                "Nonfinite or negative host energy dissipation")
        # Exact identity for backward-Euler electrical winding update;
        # its RHS is numerical dissipation, NOT a semiconductor loss.
        electrical_residual = ein-ediode-ecopper-ebemf-emag
        tol = 1e-8*max(1.0, *(abs(x) for x in values))
        if abs(electrical_residual-euler_current_loss) > tol:
            raise AssertionError(
                "Ideal-diode/current energy identity did not close")
        self.iabc[:] = new_i
        self.omega_mech_rad_s = new_omega
        self.angle_mech_rad = new_angle
        self.last_conduction = solution
        self.integrated_intervals += 1
        self.diode_conduction_intervals += any(
            x in ("LOW_DIODE", "HIGH_DIODE") for x in solution.states)
        self.bus_input_j += ein
        self.diode_loss_j += ediode
        self.copper_loss_j += ecopper
        self.friction_loss_j += efriction
        self.load_loss_j += eload
        self.bemf_conversion_j += ebemf
        self.shaft_conversion_j += eshaft
        self.magnetic_delta_j += emag
        self.kinetic_delta_j += ekin
        self.raw_residual_j += raw
        self.abs_residual_j += abs(raw)
        self.max_step_residual_j = max(
            self.max_step_residual_j, abs(raw))
        self.backward_euler_current_numerical_loss_j += euler_current_loss
        return self.sample(
            gate_enabled=any(s != "Z" for s in self.topology.legs))

    def diagnostics(self):
        return {
            "scope": "HOST_ONLY_EXPLICIT_LEG_IDEAL_DIODE_CURRENT_CONTINUITY",
            "model_assumptions": (
                "INSTANTANEOUS_EXPLICIT_H_L_Z;BACKWARD_EULER;"
                "IDEAL_DIODE_FIXED_DROP;NO_REAL_PWM_EDGE_INFORMATION"),
            "intervals": self.integrated_intervals,
            "topology_changes": self.topology_changes,
            "first_topology_events": self.first_topology_events,
            "diode_conduction_intervals": self.diode_conduction_intervals,
            "last_switches": list(self.topology.legs),
            "last_active_states": (
                list(self.last_conduction.states)
                if self.last_conduction else None),
            "last_phase_currents_a": list(self.iabc),
            "last_magnetic_energy_j": self.magnetic_energy_j,
            "bus_input_energy_j": self.bus_input_j,
            "winding_copper_loss_j": self.copper_loss_j,
            "diode_loss_j": self.diode_loss_j,
            "viscous_loss_j": self.friction_loss_j,
            "load_loss_j": self.load_loss_j,
            "winding_magnetic_delta_j": self.magnetic_delta_j,
            "rotor_kinetic_delta_j": self.kinetic_delta_j,
            "bemf_conversion_j": self.bemf_conversion_j,
            "shaft_electromagnetic_work_j": self.shaft_conversion_j,
            "backward_euler_electrical_numerical_loss_j": (
                self.backward_euler_current_numerical_loss_j),
            "forced_current_projection_impulse_energy_j": (
                self.forced_current_projection_impulse_j),
            "raw_energy_residual_j": self.raw_residual_j,
            "sum_abs_energy_residual_j": self.abs_residual_j,
            "max_abs_step_energy_residual_j": self.max_step_residual_j,
            "physical_motor_qualified": False,
            "real_native_guest_PWM_or_CAP1_qualified": False,
            "numeric_timestep_convergence_qualified": False,
        }
