#!/usr/bin/env python3
"""Per-integration energy accounting for the G13B3 SIM_ONLY open-star plant.

This is an audit of the EXISTING sampled-hold numerical implementation,
not an alternative motor solver. The old solver intentionally projects
the three-phase current onto one active branch at every commutation.
That nonphysical instantaneous projection must be separately exposed,
not hidden in a seemingly closed continuous-time energy balance.

All values in J; no physical-model, efficiency, or strict-rotor PASS.
"""
import math


class NativeModelEnergyLedger:
    """Bounded event history plus complete cumulative per-step accounting."""

    def __init__(self, p):
        self.p = p
        self.intervals = 0
        self.powered_intervals = 0
        self.coasting_intervals = 0
        self.time_s = 0.0
        self.input_j = 0.0
        self.copper_j = 0.0
        self.viscous_j = 0.0
        self.load_j = 0.0
        self.kinetic_change_j = 0.0
        self.magnetic_change_j = 0.0
        self.topology_impulse_j = 0.0
        self.topology_impulse_abs_j = 0.0
        self.electrical_bemf_work_j = 0.0
        self.mechanical_torque_work_j = 0.0
        self.raw_balance_residual_j = 0.0
        self.integration_balance_residual_j = 0.0
        self.absolute_integration_residual_j = 0.0
        self.max_abs_step_integration_residual_j = 0.0
        self.topology_change_count = 0
        self.topology_nonzero_impulses = 0
        self.topology_events = []
        self.last_power_pair = None

    def _accumulate(self, *, dt, kind, e_in, copper, friction, load,
                    kinetic, magnetic, impulse, e_bemf, e_torque,
                    prior_pair=None, active_pair=None, old_iabc=None,
                    projected_i=None):
        values = (dt, e_in, copper, friction, load, kinetic,
                  magnetic, impulse, e_bemf, e_torque)
        if not all(math.isfinite(x) for x in values) or dt <= 0:
            raise FloatingPointError("Nonfinite or nonpositive SIM_ONLY energy step")
        if min(copper, friction, load) < -1e-12:
            raise FloatingPointError("Negative physical dissipation in energy ledger")

        # The model's instantaneous current projection is NOT accounted
        # for by the winding differential equation. Raw residual includes
        # that discontinuity; integration-only residual explicitly removes
        # its signed energy jump without claiming the impulse is physical.
        raw = e_in - copper - friction - load - kinetic - magnetic
        integration = raw + impulse
        if not math.isfinite(raw) or not math.isfinite(integration):
            raise FloatingPointError("Nonfinite SIM_ONLY energy residual")
        self.intervals += 1
        self.powered_intervals += (kind == "powered")
        self.coasting_intervals += (kind == "coast")
        self.time_s += dt
        self.input_j += e_in
        self.copper_j += copper
        self.viscous_j += friction
        self.load_j += load
        self.kinetic_change_j += kinetic
        self.magnetic_change_j += magnetic
        self.topology_impulse_j += impulse
        self.topology_impulse_abs_j += abs(impulse)
        self.electrical_bemf_work_j += e_bemf
        self.mechanical_torque_work_j += e_torque
        self.raw_balance_residual_j += raw
        self.integration_balance_residual_j += integration
        self.absolute_integration_residual_j += abs(integration)
        self.max_abs_step_integration_residual_j = max(
            self.max_abs_step_integration_residual_j, abs(integration))
        if prior_pair != active_pair:
            self.topology_change_count += 1
            if abs(impulse) > 1e-18:
                self.topology_nonzero_impulses += 1
                if len(self.topology_events) < 12:
                    self.topology_events.append({
                        "integration_interval": self.intervals,
                        "previous_pair": list(prior_pair) if prior_pair else None,
                        "next_pair": list(active_pair) if active_pair else None,
                        "old_currents_a": list(old_iabc),
                        "projected_branch_current_a": projected_i,
                        "instantaneous_magnetic_energy_change_j": impulse,
                        "physically_resolved_commutation": False,
                    })
        self.last_power_pair = active_pair

    def powered(self, *, dt, before_currents, after_branch_current,
                projected_branch_current, source, sink, branch_voltage,
                old_line_bemf, torque, omega_before, omega_after):
        if source == sink or source not in range(3) or sink not in range(3):
            raise ValueError("Invalid source/return energy ledger pair")
        if len(before_currents) != 3:
            raise ValueError("Three prior winding currents required")
        p = self.p
        prev_mag = 0.5 * p.phase_inductance_h * sum(
            i*i for i in before_currents)
        projected_mag = p.phase_inductance_h * projected_branch_current**2
        next_mag = p.phase_inductance_h * after_branch_current**2
        avg_i = (projected_branch_current + after_branch_current) * 0.5
        # Interpret the Euler current endpoints with linear interpolation.
        # This is a numerical audit, not a claim about the actual PWM waveform.
        copper = 2 * p.phase_resistance_ohm * dt / 3 * (
            projected_branch_current**2 +
            projected_branch_current * after_branch_current +
            after_branch_current**2)
        omega_mean = (omega_before + omega_after) * 0.5
        friction = p.viscous_friction_nm_per_rad_s * dt / 3 * (
            omega_before**2 + omega_before * omega_after +
            omega_after**2)
        load = p.load_torque_nm * abs(omega_mean) * dt
        kinetic = 0.5 * p.inertia_kg_m2 * (
            omega_after**2 - omega_before**2)
        self._accumulate(
            dt=dt, kind="powered",
            e_in=branch_voltage * avg_i * dt,
            copper=copper, friction=friction, load=load,
            kinetic=kinetic, magnetic=next_mag-prev_mag,
            impulse=projected_mag-prev_mag,
            e_bemf=old_line_bemf * avg_i * dt,
            e_torque=torque * omega_mean * dt,
            prior_pair=self.last_power_pair,
            active_pair=(source, sink),
            old_iabc=before_currents, projected_i=projected_branch_current)

    def coast(self, *, dt, before_currents, omega_before, omega_after):
        p = self.p
        old_mag = 0.5 * p.phase_inductance_h * sum(
            i*i for i in before_currents)
        # Existing model discards ALL winding current upon opening.
        friction = p.viscous_friction_nm_per_rad_s * dt / 3 * (
            omega_before**2 + omega_before * omega_after +
            omega_after**2)
        load = p.load_torque_nm * abs(
            (omega_before + omega_after) * 0.5) * dt
        kinetic = 0.5 * p.inertia_kg_m2 * (
            omega_after**2 - omega_before**2)
        self._accumulate(
            dt=dt, kind="coast", e_in=0.0, copper=0.0,
            friction=friction, load=load, kinetic=kinetic,
            magnetic=-old_mag, impulse=-old_mag,
            e_bemf=0.0, e_torque=0.0,
            prior_pair=self.last_power_pair, active_pair=None,
            old_iabc=before_currents, projected_i=0.0)

    def result(self):
        return {
            "scope": "SIM_ONLY_SAMPLED_HOLD_NUMERICAL_ENERGY_DIAGNOSTIC",
            "integration_intervals": self.intervals,
            "powered_intervals": self.powered_intervals,
            "coasting_intervals": self.coasting_intervals,
            "integrated_s": self.time_s,
            "model_bus_input_energy_j": self.input_j,
            "winding_copper_loss_energy_j": self.copper_j,
            "viscous_friction_loss_energy_j": self.viscous_j,
            "load_loss_energy_j": self.load_j,
            "mechanical_kinetic_energy_change_j": self.kinetic_change_j,
            "winding_magnetic_energy_change_j": self.magnetic_change_j,
            "topology_projection_impulse_energy_j": self.topology_impulse_j,
            "topology_projection_absolute_energy_j": self.topology_impulse_abs_j,
            "bemf_electrical_conversion_work_j": self.electrical_bemf_work_j,
            "shaft_electromagnetic_conversion_work_j": self.mechanical_torque_work_j,
            "raw_energy_balance_residual_j": self.raw_balance_residual_j,
            "integration_residual_excluding_topology_impulses_j":
                self.integration_balance_residual_j,
            "sum_abs_integration_residual_j":
                self.absolute_integration_residual_j,
            "max_abs_step_integration_residual_j":
                self.max_abs_step_integration_residual_j,
            "topology_change_count": self.topology_change_count,
            "topology_nonzero_impulses": self.topology_nonzero_impulses,
            "first_topology_events": list(self.topology_events),
            "numerical_energy_balance_qualified": False,
            "commutation_current_continuity_qualified": False,
            "physical_motor_calibrated": False,
            "native_rotor_direction_qualified_by_this_ledger": False,
        }
