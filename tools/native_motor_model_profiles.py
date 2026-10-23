#!/usr/bin/env python3
"""Pinned E62 SIM_ONLY motor-model A/B profiles; no hardware calibration.

bemf_constant_v_per_rad_s is Ke per *electrical* rad/s in the existing
VirtualBLDC.sample(), i.e. e_phase = Ke * pole_pairs * omega_mech * sin(theta).
Torque is Te = Kt * sum(i_phase * sin(theta_phase)). For instantaneous
electromagnetic power reciprocity, Kt = Ke * pole_pairs.

This identity is necessary, NOT sufficient for energy conservation in the
sampled-hold Euler plant, nor proof of a real E62 motor's constants.
"""
from .virtual_bldc import MotorParameters

PROFILES = ("legacy", "reciprocal")


def native_motor_parameters(profile="legacy"):
    if profile not in PROFILES:
        raise ValueError("Only pinned SIM_ONLY legacy/reciprocal A/B profiles")
    ke_electrical = 0.02
    poles = 7
    kt = ke_electrical * poles if profile == "reciprocal" else 0.02
    return MotorParameters(
        vbus_v=24.0,
        phase_resistance_ohm=0.3,
        phase_inductance_h=0.002,
        bemf_constant_v_per_rad_s=ke_electrical,
        torque_constant_nm_per_a=kt,
        inertia_kg_m2=1e-6,
        viscous_friction_nm_per_rad_s=0.0001,
        load_torque_nm=0.0,
        pole_pairs=poles,
    )


def native_motor_model_metadata(profile):
    p = native_motor_parameters(profile)
    ratio = (p.bemf_constant_v_per_rad_s * p.pole_pairs /
             p.torque_constant_nm_per_a)
    return {
        "profile": profile,
        "scope": "SIM_ONLY_UNCALIBRATED_AB_EXPERIMENT",
        "ke_reference": "PHASE_PEAK_V_PER_ELECTRICAL_RAD_PER_SEC",
        "bemf_constant_v_per_electrical_rad_s": p.bemf_constant_v_per_rad_s,
        "torque_constant_nm_per_a": p.torque_constant_nm_per_a,
        "pole_pairs": p.pole_pairs,
        "electromagnetic_power_ratio_pe_over_pm": ratio,
        "electromagnetic_reciprocal": profile == "reciprocal",
        "integrator": "SAMPLED_HOLD_EULER_TWO_TERMINAL_RESET_CURRENT_AT_COMMUTATION",
        "physical_motor_calibrated": False,
    }
