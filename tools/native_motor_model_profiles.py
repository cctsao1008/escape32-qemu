#!/usr/bin/env python3
"""Named E62 SIM_ONLY motor models driven by observed original-Guest PWM.

'legacy' and 'reciprocal' remain unchanged historical host A/B fixtures.
ECX87 values come from maxon EC 87 flat UAV April 2025 datasheet, p.1.
Phase R/L = half the listed line-to-line value (balanced star assumption).
Published terminal-equivalent Kt matches 60/(2*pi*Kv). For the explicit
balanced-sine star model use K_phase=Kt_terminal/sqrt(3), and both
phase-peak BEMF and torque share K_phase for power reciprocity.
The actual phase waveform, driver and propeller are NOT calibrated.
No propeller inertia, propeller torque curve or silicon analog frontend.
"""
import math

from .virtual_bldc import MotorParameters

APC_STUDY_PROFILES = (
    "ecx87-kv210-apc24x12e-47v-j1",
    "ecx87-kv210-apc24x12e-47v-j2",
    "ecx87-kv210-apc24x12e-47v-j5",
)
DATASHEET_PROFILES = ("ecx87-kv147", "ecx87-kv210")
QEMU_MOTOR_PROFILES = DATASHEET_PROFILES + APC_STUDY_PROFILES
# Preserve the historical host A/B fixture public API (four entries).
# APC products are a separate opt-in QEMU study, not old PROFILES.
PROFILES = ("legacy", "reciprocal") + DATASHEET_PROFILES
_ECX87 = {
    "ecx87-kv147": {
        "part_number": "773484",
        "kv_rpm_per_v": 147.0,
        "kt_nm_per_a": 0.0649,
        "line_resistance_ohm": 0.106,
        "line_inductance_h": 0.000048,
    },
    "ecx87-kv210": {
        "part_number": "NEW KV210 (no part number specified on datasheet p.1)",
        "kv_rpm_per_v": 210.0,
        "kt_nm_per_a": 0.0454,
        "line_resistance_ohm": 0.0566,
        "line_inductance_h": 0.0000175,
    },
}
ECX87_POLE_PAIRS = 21
ECX87_ROTOR_INERTIA_KG_M2 = 1300.0 * 1e-7  # g*cm^2 -> kg*m^2


def native_motor_parameters(profile="legacy"):
    if profile not in PROFILES and profile not in APC_STUDY_PROFILES:
        raise ValueError("Unknown explicit SIM_ONLY motor profile: " + str(profile))
    if profile in QEMU_MOTOR_PROFILES:
        apc = profile in APC_STUDY_PROFILES
        m = _ECX87["ecx87-kv210" if apc else profile]
        pole_pairs = ECX87_POLE_PAIRS
        kt_terminal = m["kt_nm_per_a"]
        # Maxon terminal Kt=60/(2*pi*Kv); the largest sinusoidal
        # line-to-line BEMF is sqrt(3)*K_phase*omega_mech.
        # Never apply terminal Kt directly as a phase-peak sine factor.
        kt_phase = kt_terminal / math.sqrt(3.0)
        if abs(kt_terminal / (60.0 / (2.0*math.pi*m["kv_rpm_per_v"])) - 1.0) > 0.01:
            raise ValueError("ECX87 terminal Kt and Kv datasheet mismatch")
        return MotorParameters(
            vbus_v=47.0 if apc else 24.0,
            phase_resistance_ohm=m["line_resistance_ohm"] / 2.0,
            phase_inductance_h=m["line_inductance_h"] / 2.0,
            bemf_constant_v_per_rad_s=kt_phase / pole_pairs,
            torque_constant_nm_per_a=kt_phase,
            inertia_kg_m2=ECX87_ROTOR_INERTIA_KG_M2 *
                (int(profile[-1]) if apc else 1),
            # Uncalibrated simulator assumptions, NOT maxon datasheet.
            viscous_friction_nm_per_rad_s=0.0001,
            load_torque_nm=0.0,
            pole_pairs=pole_pairs,
        )
    # Preserve pinned G13B3M comparison numbers exactly.
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
    meta = {
        "profile": profile,
        "scope": "SIM_ONLY_UNCALIBRATED_AB_EXPERIMENT",
        "ke_reference": "PHASE_PEAK_V_PER_ELECTRICAL_RAD_PER_SEC",
        "bemf_constant_v_per_electrical_rad_s": p.bemf_constant_v_per_rad_s,
        "torque_constant_nm_per_a": p.torque_constant_nm_per_a,
        "pole_pairs": p.pole_pairs,
        "motor_poles_for_escape32_telem_poles": p.pole_pairs * 2,
        "vbus_v": p.vbus_v,
        "phase_resistance_ohm": p.phase_resistance_ohm,
        "phase_inductance_h": p.phase_inductance_h,
        "rotor_inertia_kg_m2": p.inertia_kg_m2,
        "viscous_friction_nm_per_rad_s": p.viscous_friction_nm_per_rad_s,
        "load_torque_nm": p.load_torque_nm,
        "electromagnetic_power_ratio_pe_over_pm": ratio,
        "electromagnetic_reciprocal": abs(ratio - 1.0) < 1e-12,
        "integrator": ("EVENT_HISTORY_CURRENT_CONTINUOUS" if
                       profile in DATASHEET_PROFILES else
                       "SAMPLED_HOLD_EULER_TWO_TERMINAL_RESET_CURRENT_AT_COMMUTATION"),
        "physical_motor_calibrated": False,
        "propeller_inertia_and_load_modeled": profile in APC_STUDY_PROFILES,
    }
    if profile in QEMU_MOTOR_PROFILES:
        apc = profile in APC_STUDY_PROFILES
        m = _ECX87["ecx87-kv210" if apc else profile]
        meta.update(
            source="MAXON_EC_87_FLAT_UAV_APR_2025_DATASHEET_PAGE_1",
            datasheet_part_number=m["part_number"],
            published_kv_rpm_per_v=m["kv_rpm_per_v"],
            published_kt_nm_per_a=m["kt_nm_per_a"],
            phase_peak_flux_constant_v_s_per_rad=p.torque_constant_nm_per_a,
            sine_basis_to_terminal_ll_peak=math.sqrt(3.0),
            predicted_no_load_terminal_bemf_v_at_3500rpm=(
                math.sqrt(3.0)*p.torque_constant_nm_per_a*
                3500.0*2.0*math.pi/60.0),
            published_line_to_line_resistance_ohm=m["line_resistance_ohm"],
            published_line_to_line_inductance_h=m["line_inductance_h"],
            winding_assumption="BALANCED_STAR_PHASE_R_AND_L_ARE_HALF_LINE_TO_LINE",
            ke_convention_assumption=(
                "BALANCED_STAR_SINE_PHASE_PEAK_EQUALS_PUBLISHED_TERMINAL_KT_OVER_SQRT3_ASSUMED"),
            frontend_model="UNCHANGED_SIM_ONLY_1P65V_BIAS_0P02_GAIN",
            caveat=("APC_ANALYTICAL_STATIC_TORQUE_AND_GUESSED_J_NOT_HARDWARE"
                    if apc else "MOTOR_ONLY_UNCALIBRATED_NOT_PROPELLER_OR_HARDWARE"),
        )
        if apc:
            meta.update(
                model_source="MAXON_APR2025_AND_APC_PER3_24x12E_v2022_0915",
                propeller_static_torque_model="APC_V0_MPH_1000_TO_6000RPM",
                propeller_torque_nm_grid=[0.132,0.494,1.085,1.913,2.996,4.362],
                propeller_inertia_ratio_to_motor=int(profile[-1]),
                propeller_inertia_measured=False,
                propeller_inertia_and_load_modeled=True,
                static_airflow_assumption=True,
                product_voltage_assumption_v=47.0,
            )
    else:
        meta["source"] = "PINNED_LEGACY_SIM_ONLY_TEST_VALUES"
    return meta
