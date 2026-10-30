#!/usr/bin/env python3
"""E62 #5/#7 SIM_ONLY profile contract tied to the effective QEMU plant.

No profile claims real silicon, hardware qualification or rotor direction.
Do not interpret the 1kHz QEMU *diagnostic* as an ADC sampling rate.
The actual QEMU numeric model is checked via QTest MMIO in the runner.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from tools.native_motor_model_profiles import (
    DATASHEET_PROFILES,native_motor_parameters,native_motor_model_metadata)

ROOT=Path(__file__).resolve().parents[1]
DEFAULT=ROOT/"configs/e62-sim-profile-matrix-v1.json"
TOP={"schema","scope","motor_plant_simulation","analog_frontend_simulation",
     "current_sensor_simulation","passive_reacquisition_study",
     "protection_study","profiles"}

def finite_number(v, label):
    if type(v) not in (float,int) or not math.isfinite(v):
        raise ValueError("Invalid SIM profile numeric value: "+label)
    return float(v)

def near(value, expected, label):
    if not math.isclose(finite_number(value,label),expected,rel_tol=1e-9,abs_tol=1e-12):
        raise ValueError("SIM profile disagrees with existing QEMU source model: "+label)

def load(path=DEFAULT):
    raw=Path(path).read_bytes()
    if len(raw)>16384:
        raise ValueError("Unbounded SIM profile JSON")
    data=json.loads(raw)
    if type(data) is not dict or set(data)!=TOP or (
            data["schema"]!="e62.sim.model-profile-matrix.v1" or
            data["scope"]!="SIM_ONLY_NATIVE_QEMU_NO_PHYSICAL_CALIBRATION"):
        raise ValueError("Unknown SIM profile schema/scope")
    motor=data["motor_plant_simulation"]
    if type(motor) is not dict or set(motor)!={
            "virtual_bus_v","tick_ns","phase_model",
            "phase_r_l_from_line_to_line_factor",
            "terminal_kt_to_phase_peak_factor",
            "viscous_friction_nm_per_rad_s","load_torque_nm"}:
        raise ValueError("Incomplete QEMU motor parameter contract")
    near(motor["virtual_bus_v"],24.0,"virtual_bus_v")
    if type(motor["tick_ns"]) is not int or motor["tick_ns"]!=1000:
        raise ValueError("Model physics timing must match actual QEMU 1us")
    if motor["phase_model"]!="BALANCED_STAR_SINUSOIDAL" or (
            motor["terminal_kt_to_phase_peak_factor"]!="1/sqrt(3)"):
        raise ValueError("Phase/terminal motor convention mismatch")
    near(motor["phase_r_l_from_line_to_line_factor"],.5,"phase R/L ratio")
    near(motor["viscous_friction_nm_per_rad_s"],.0001,"friction")
    near(motor["load_torque_nm"],0.0,"load")
    adc=data["analog_frontend_simulation"]
    if type(adc) is not dict or set(adc)!={
            "adc_bits","adc_vref_v","bemf_bias_v","bemf_gain_v_per_v",
            "diagnostic_hz","diagnostic_is_adc_sampling_clock"}:
        raise ValueError("Incomplete QEMU analog frontend contract")
    if type(adc["adc_bits"]) is not int or adc["adc_bits"]!=12 or (
            type(adc["diagnostic_hz"]) is not int or adc["diagnostic_hz"]!=1000 or
            adc["diagnostic_is_adc_sampling_clock"] is not False):
        raise ValueError("QEMU diagnostics cannot impersonate ADC sampling")
    for key,expected in (("adc_vref_v",3.3),("bemf_bias_v",1.65),
                         ("bemf_gain_v_per_v",.02)):
        near(adc[key],expected,key)
    oc=data["current_sensor_simulation"]
    if type(oc) is not dict or set(oc)!={
            "adc_code_zero_current","adc_codes_per_abs_amp",
            "overrange_fault_code","measures_actual_motor_current"}:
        raise ValueError("Incomplete QEMU OC source contract")
    if any(type(oc[k]) is not int for k in (
            "adc_code_zero_current","adc_codes_per_abs_amp","overrange_fault_code")) or (
            oc["adc_code_zero_current"]!=1000 or oc["adc_codes_per_abs_amp"]!=4 or
            oc["overrange_fault_code"]!=4095 or
            oc["measures_actual_motor_current"] is not False):
        raise ValueError("QEMU current/OC source disagrees with model")
    study=data["passive_reacquisition_study"]
    if type(study) is not dict or set(study)!={
            "min_adjacent_phase_delta_codes","coast_ms","rpm_grid",
            "rank_events_per_electrical_revolution",
            "diagnostic_samples_per_sector_target","output_may_authorize_rearm"}:
        raise ValueError("Incomplete passive observer simulation study")
    if (type(study["min_adjacent_phase_delta_codes"]) is not int or
        not 1<=study["min_adjacent_phase_delta_codes"]<=4095 or
        study["coast_ms"]!=[300,1500,3000] or
        study["rank_events_per_electrical_revolution"]!=6 or
        type(study["diagnostic_samples_per_sector_target"]) is not int or
        not 2<=study["diagnostic_samples_per_sector_target"]<=20 or
        study["output_may_authorize_rearm"] is not False or
        type(study["rpm_grid"]) is not list or not study["rpm_grid"] or
        any(type(x) is not int or not 1<=x<=6000 for x in study["rpm_grid"]) or
        study["rpm_grid"]!=sorted(set(study["rpm_grid"]))):
        raise ValueError("Unsafe passive study conditions")
    protection=data["protection_study"]
    if type(protection) is not dict or protection!={
        "oc_sources":["oc-u","oc-v","oc-w"],"nfault":True,
        "dshot_loss":True,"trip_latch_retention_required":True,
        "all_six_gate_off_required":True,
        "source_fault_not_physical_current":True}:
        raise ValueError("Protection fault suite must not waive safety")
    if type(data["profiles"]) is not dict or set(data["profiles"])!=set(DATASHEET_PROFILES):
        raise ValueError("Missing or unexpected motor model")
    for name,entry in data["profiles"].items():
        if type(entry) is not dict or set(entry)!={
                "kv_rpm_per_v","terminal_kt_nm_per_a",
                "line_resistance_ohm","line_inductance_h",
                "pole_pairs","rotor_inertia_kg_m2"}:
            raise ValueError("Incomplete model "+name)
        p=native_motor_parameters(name);ref=native_motor_model_metadata(name)
        for key,v in (("kv_rpm_per_v",ref["published_kv_rpm_per_v"]),
            ("terminal_kt_nm_per_a",ref["published_kt_nm_per_a"]),
            ("line_resistance_ohm",p.phase_resistance_ohm*2),
            ("line_inductance_h",p.phase_inductance_h*2),
            ("rotor_inertia_kg_m2",p.inertia_kg_m2)):
            near(entry[key],v,name+"."+key)
        if type(entry["pole_pairs"]) is not int or entry["pole_pairs"]!=p.pole_pairs:
            raise ValueError("Incorrect physical pole pair config")
        if abs(ref["electromagnetic_power_ratio_pe_over_pm"]-1)>1e-10:
            raise ValueError("Model breaks BEMF-torque reciprocity")
    return data

def report(data):
    adc=data["analog_frontend_simulation"]
    study=data["passive_reacquisition_study"]
    results=[]
    for profile in DATASHEET_PROFILES:
        motor=native_motor_parameters(profile)
        for rpm in study["rpm_grid"]:
            omega=rpm*2*math.pi/60
            # Phase code amplitude, not the minimum pairwise phase-code
            # separation near sector boundaries (that can approach zero).
            amplitude=(2**adc["adc_bits"]-1)/adc["adc_vref_v"]*(
                adc["bemf_gain_v_per_v"]*motor.torque_constant_nm_per_a*omega)
            rank_events_per_second=(
                rpm/60*motor.pole_pairs*study["rank_events_per_electrical_revolution"])
            min_samples_for_diagnostic=(study["diagnostic_samples_per_sector_target"]*
                                        rank_events_per_second)
            inadequate_code_amplitude=amplitude<study["min_adjacent_phase_delta_codes"]
            diagnostic_alias_risk=adc["diagnostic_hz"]<min_samples_for_diagnostic
            results.append({
                "profile":profile,"mechanical_rpm":rpm,
                "theoretical_phase_code_peak_amplitude":round(amplitude,4),
                "phase_sector_events_per_second":round(rank_events_per_second,4),
                "recommended_minimum_observation_hz_for_study":round(min_samples_for_diagnostic,4),
                "model_diagnostic_at_risk_of_phase_rank_alias":diagnostic_alias_risk,
                "model_BEMF_peak_below_requested_code_contrast":inadequate_code_amplitude,
                "static_phase_rank_confidence_established":False,
                "simulated_rotor_direction_or_rearm_qualified":False,
            })
    return {"schema":"e62.sim.profile-parameter-feasibility.v1",
            "classification":"SIM_ONLY_DIAGNOSTIC_NOT_END_TO_END_RECOVERY",
            "selected_motor_profiles":list(DATASHEET_PROFILES),
            "computed_points":results,"original_p1_unchanged":True,
            "hardware_qualified":False,"rearm_permitted":False,
            "separate_actual_qemu_runtime_verification_required":True}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--profile-file",type=Path,default=DEFAULT)
    ap.add_argument("--output",type=Path)
    args=ap.parse_args()
    result=report(load(args.profile_file))
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("E62_SIM_MODEL_PROFILE_FEASIBILITY "+json.dumps(result,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
