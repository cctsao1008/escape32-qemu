"""Source-derived commutation geometry vs uncalibrated rotor model defects.

This classifies likely model failure mechanisms without weakening G13B3M's
strict 12-sector + direction + energy test or changing Guest firmware.
"""
import math
from tools.native_closed_loop_audit import ORIGINAL_REL17_ROUTE
from tools.native_motor_model_profiles import native_motor_model_metadata
from tools.native_power_coupled_plant import NativePowerCoupledBLDC

def analyze_geometry(initial_electrical_deg=-30.0):
    basis=[]
    for sector in range(6):
        theta=math.radians(initial_electrical_deg+sector*60.0)
        waves=tuple(math.sin(theta+offset)
                    for offset in (0,-2*math.pi/3,2*math.pi/3))
        _,(source,sink)=ORIGINAL_REL17_ROUTE[sector+1]
        torque_basis=waves[source]-waves[sink]
        basis.append({"source_guest_step":sector+1,"source_phase":source,
                      "sink_phase":sink,
                      "electrical_deg":initial_electrical_deg+sector*60,
                      "signed_torque_per_amp_kt":torque_basis})
    return {
        "source":"PINNED_REL17_3_COMMUTATION_SEQUENCE",
        "aligned_all_six_positive_torque":
            all(x["signed_torque_per_amp_kt"]>0 for x in basis),
        "sectors":basis,
        "not_a_dynamic_rotor_direction_proof":True,
    }

def diagnose_rotor_model():
    legacy=native_motor_model_metadata("legacy")
    reciprocal=native_motor_model_metadata("reciprocal")
    return {
        "status":"FAIL_G13B3M_STRICT_ROTOR_NOT_RESOLVED_BY_STATIC_ANALYSIS",
        "source_geometry":analyze_geometry(),
        "legacy_ke_kt_power_ratio":legacy["electromagnetic_power_ratio_pe_over_pm"],
        "reciprocal_ke_kt_power_ratio":reciprocal["electromagnetic_power_ratio_pe_over_pm"],
        "legacy_forced_current_projection_at_each_commutation":True,
        "current_continuous_explicit_diodes_model_available":True,
        "root_cause_conclusions":[
            "PINNED_GUEST_SOURCE_SIX_STEP_ORDER_HAS_FORWARD_TORQUE_AT_DECLARED_ALIGNMENT",
            "LEGACY_KT_KE_ENERGY_NONRECIPROCITY_CORRUPTS_MODEL_POWER",
            "LEGACY_CURRENT_PROJECTION_INTRODUCES_UNMODELED_MAGNETIC_ENERGY_IMPULSE",
            "ROTOR_REVERSAL_DYNAMIC_CAUSAL_ROOT_OPEN_PENDING_TRUE_CLOCKED_FEEDBACK",
        ],
        "physical_motor_calibrated":False,
        "strict_native_rotor_direction_qualified":False,
    }
