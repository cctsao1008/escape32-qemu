#!/usr/bin/env python3
"""Versioned E62 #5 SIM_ONLY case profile resolver and effective-QEMU oracle.

The Original Rel17.3 firmware and strict P1 oracle are immutable DUT/gates.
This file never edits, flashes, or commands Guest registers. Profile
resolution MUST NOT turn any model assumption into a hardware PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.native_dshot_scenario import load_native_scenario, SHA
from tools.native_motor_model_profiles import native_motor_parameters, QEMU_MOTOR_PROFILES
from tools.e62_apc24x12e_static import load as load_apc_source

DEFAULT = ROOT / "configs/e62-sim-case-profiles-v1.json"
_PROFILE_MAP = {
    "BASE-KV147-24V-NOPROP": ("ecx87-kv147",147,53000,24000,64900,24000,1,False),
    "BASE-KV210-24V-NOPROP": ("ecx87-kv210",210,28300,8750,45400,24000,1,False),
    "QB-KV210-47V-APC24X12E-J1": ("ecx87-kv210-apc24x12e-47v-j1",210,28300,8750,45400,47000,1,True),
    "QB-KV210-47V-APC24X12E-J2": ("ecx87-kv210-apc24x12e-47v-j2",210,28300,8750,45400,47000,2,True),
    "QB-KV210-47V-APC24X12E-J5": ("ecx87-kv210-apc24x12e-47v-j5",210,28300,8750,45400,47000,5,True),
}
_SCENARIOS = {
    300: ("scenarios/e62-experimental-two-demand-coast-short300.json",5100),
    1500: ("scenarios/e62-experimental-two-demand-coast-medium1500.json",6300),
    3000: ("scenarios/e62-experimental-two-demand-coast-long3000.json",7800),
}
_BEMF_SOURCE = "APC_24x12E_V0MPH_ANALYTICAL"


def load(path=DEFAULT):
    raw = Path(path).read_bytes()
    if len(raw)>32768:
        raise ValueError("Oversized E62 SIM profile registry")
    data = json.loads(raw)
    required = {"schema","scope","guest","source_contract","model_sources","scenarios","profiles"}
    if type(data) is not dict or set(data)!=required or (
        data["schema"]!="e62.sim.case-profiles.v1" or
        data["scope"]!="SIM_ONLY_SOURCE_PROFILE_NO_FIRMWARE_EDIT"):
        raise ValueError("Unknown E62 SIM case profile schema/scope")
    guest=data["guest"]
    if (type(guest) is not dict or guest != {
        "kind":"PINNED_ORIGINAL_REL17_3",
        "relative_elf_path":"baseline/e62-g13b3/firmware/AM13E-rev17.3.elf",
        "sha256":SHA,"source_built_candidate_allowed":False,
        "modify_firmware_for_sitl":False}):
        raise ValueError("Profile must pin immutable Original Guest")
    contract=data["source_contract"]
    if (type(contract) is not dict or contract != {
        "dshot_protocol":"DSHOT600","frame_period_ns":1000000,
        "guest_ready_gating":False,"phase_initial_electrical_degrees":-30,
        "actual_qemu_effective_readback_required":True,
        "guest_rotor_angle_injection":False,"host_guest_register_writes":False,
        "original_p1_criteria_unchanged":True,
        "reacquisition_qualified_by_profile":False,
        "hardware_qualified":False}):
        raise ValueError("Unsafe profile source/safety/permission contract")
    sources=data["model_sources"]
    if (type(sources) is not dict or sources != {
        "maxon":"maxon EC 87 flat UAV datasheet, Apr 2025, p.1",
        "apc":"APC PER3_24x12E.dat v2022-0915 2022-09-22; static V=0 mph; 0-6000 rpm; analytical not bench",
        "apc_interpolation":"LINEAR_1000_TO_6000_BELOW_1000_QUADRATIC",
        "apc_negative_speed":"SIGN_SYMMETRIC_SIM_ASSUMPTION_NOT_VALIDATED_WINDMILL",
        "unknown_propeller_inertia":"J1/J2/J5 only; no measured prop/hub inertia"}):
        raise ValueError("Unsupported/unproven simulator source provenance")
    load_apc_source()
    cases=data["profiles"]
    if (type(cases) is not list or len(cases)!=5 or
        [x.get("id") if type(x) is dict else None for x in cases]!=list(_PROFILE_MAP)):
        raise ValueError("Missing, reordered, duplicated or unknown case profile")
    for case in cases:
        name,kv,r,l,kt,bus,j,apc=_PROFILE_MAP[case["id"]]
        expected={
            "id":case["id"],"qemu_motor_profile":name,
            "qualification_class":("ANALYTICAL_PROP_SENSITIVITY" if apc else "HISTORICAL_MOTOR_ONLY"),
            "source_identity":("MAXON_MOTOR_AND_APC_ANALYTICAL_STATIC"
                               if apc else "MAXON_MOTOR_DATASHEET_AND_HISTORICAL_SIM"),
            "motor":"maxon EC 87 flat UAV",
            "published_kv_rpm_per_v":kv,
            "phase_resistance_microohm":r,
            "phase_inductance_nanohenry":l,
            "terminal_kt_micro_nm_per_a":kt,
            "dc_bus_millivolts":bus,
            "propeller_model":_BEMF_SOURCE if apc else "NO_PROPELLER",
            "effective_total_inertia_nano_kg_m2":130000*j,
            "effective_inertia_ratio_to_motor":j,
            "propeller_inertia_measured":False,
            "product_hardware_calibrated":False,
            "guest_motor_permission_from_profile":False,
        }
        if case!=expected or any(type(case[k]) is not type(v)
                                 for k,v in expected.items()):
            raise ValueError("Motor/apc profile parameters or trust level changed: "+case["id"])
        if name not in QEMU_MOTOR_PROFILES:
            raise ValueError("QEMU machine rejects named profile "+name)
        p=native_motor_parameters(name)
        if (round(p.vbus_v*1000)!=bus or
            round(p.inertia_kg_m2*1e9)!=130000*j or
            round(p.phase_resistance_ohm*1e6)!=r or
            round(p.phase_inductance_h*1e9)!=l):
            raise ValueError("Python motor source differs from case profile: "+name)
    sc=data["scenarios"]
    if (type(sc) is not list or len(sc)!=3 or
        [s.get("coast_ms") if type(s) is dict else None for s in sc]!=list(_SCENARIOS)):
        raise ValueError("Missing/reordered or unrecognized coast scenario")
    for s in sc:
        coast=s["coast_ms"]
        file,frames=_SCENARIOS[coast]
        if (s!={"coast_ms":coast,"file":file,"expected_dshot_frames":frames}
            or type(s["coast_ms"]) is not int or
            type(s["expected_dshot_frames"]) is not int):
            raise ValueError("Scenario path, frames or coast altered")
        stages,meta=load_native_scenario(ROOT/file)
        if (meta["original_elf_sha256"]!=SHA or
            meta["dshot_frames"]!=frames or
            stages!=[(1500,0,0,1),(1500,200,200,1),(coast,0,0,1),
                     (1500,200,200,1),(300,0,0,1)]):
            raise ValueError("Real DShot stages are not the promised coast profile")
    return data


def resolve(data,profile_id,coast_ms):
    profile=next((p for p in data["profiles"] if p["id"]==profile_id),None)
    scenario=next((s for s in data["scenarios"] if s["coast_ms"]==coast_ms),None)
    if profile is None or scenario is None:
        raise ValueError("Unknown exact case ID or coast length")
    return {**profile,
            "coast_ms":coast_ms,
            "scenario_path":scenario["file"],
            "expected_dshot_frames":scenario["expected_dshot_frames"],
            "guest_elf_path":data["guest"]["relative_elf_path"],
            "guest_elf_sha256":SHA,
            "qemu_command_line_motor_property":"esc-sim-native-motor-profile="+profile["qemu_motor_profile"],
            "simulation_only":True,
            "original_p1_unchanged":True}


def verify_readback(plan,evidence):
    """Check actual native QTest numeric readback; never infer from CLI label."""
    failures=[]
    def require(ok,msg):
        if not ok: failures.append(msg)
    expected={
        "kv_rpm_per_v":plan["published_kv_rpm_per_v"],
        "phase_resistance_microohm":plan["phase_resistance_microohm"],
        "phase_inductance_nanohenry":plan["phase_inductance_nanohenry"],
        "terminal_kt_micro_nm_per_a":plan["terminal_kt_micro_nm_per_a"],
        "bus_millivolts":plan["dc_bus_millivolts"],
        "configured_initial_electrical_mdeg":-30000,
    }
    require(evidence.get("original_elf_sha256")==SHA,"ELF_SHA_NOT_ORIGINAL")
    require(evidence.get("experimental_candidate_not_original") is False,
            "SOURCE_CANDIDATE_NOT_ORIGINAL")
    require(evidence.get("host_guest_register_writes") is False,
            "GUEST_REGISTER_WRITE_NOT_PROVEN_ABSENT")
    require(evidence.get("used_guest_wfi_or_gdb") is False,
            "WFI_OR_GDB_USED")
    require(evidence.get("physical_motor_qualified") is False,
            "PHYSICAL_QUALIFICATION_NOT_FALSE")
    e=evidence.get("effective_sim_profile") or {}
    require(e.get("name")==plan["qemu_motor_profile"],"PROFILE_SELECTION_MISMATCH")
    require(e.get("checked_against_named_model") is True,
            "ACTUAL_MODEL_CHECK_MISSING")
    require(e.get("effective_parameters")==expected,"EFFECTIVE_MODEL_READBACK_MISMATCH")
    before=(evidence.get("motor_before") or {}).get("effective_sim_motor_model")
    require(before==expected,"INITIAL_MODEL_READBACK_MISMATCH")
    prop=(evidence.get("motor_before") or {}).get("sim_propeller_source") or {}
    enabled=plan["propeller_model"]!="NO_PROPELLER"
    require(prop.get("apc24x12e_static_enabled") is enabled,"PROP_SOURCE_MISMATCH")
    require(prop.get("effective_total_inertia_nano_kg_m2")==
            plan["effective_total_inertia_nano_kg_m2"],"INERTIA_READBACK_MISMATCH")
    require(prop.get("inertia_ratio_to_motor")==(
            plan["effective_inertia_ratio_to_motor"] if enabled else 0),
            "INERTIA_RATIO_MISMATCH")
    stages,meta=load_native_scenario(ROOT/plan["scenario_path"])
    require((evidence.get("native_dshot_scenario") or {}).get("sha256")==
            meta["sha256"],"SOURCE_SCENARIO_SHA_MISMATCH")
    require(evidence.get("configured_dshot_frames")==plan["expected_dshot_frames"],
            "SOURCE_DSHOT_FRAMES_CHANGED")
    require((evidence.get("autonomous_dshot") or {}).get("sent")==
            plan["expected_dshot_frames"],"DROPPED_DSHOT_SOURCE_FRAMES")
    return {
        "schema":"e62.sim.case-profile-readback.v1",
        "case_id":plan["id"],"coast_ms":plan["coast_ms"],
        "source_profile_readback_pass":not failures,
        "failures":failures,
        "hardware_qualified":False,
        "original_p1_qualified_by_profile":False,
        "not_an_autonomous_restart_verdict":True,
    }


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config",type=Path,default=DEFAULT)
    ap.add_argument("--profile-id",choices=tuple(_PROFILE_MAP))
    ap.add_argument("--coast-ms",type=int,choices=tuple(_SCENARIOS))
    ap.add_argument("--field",choices=("qemu_motor_profile","scenario_path",
                "guest_elf_path","guest_elf_sha256","coast_ms"))
    ap.add_argument("--evidence",type=Path)
    ap.add_argument("--output",type=Path)
    args=ap.parse_args()
    try:
        data=load(args.config)
        if (args.profile_id is None)!=(args.coast_ms is None):
            raise ValueError("Select both --profile-id and --coast-ms")
        if args.field and args.profile_id is None:
            raise ValueError("--field requires resolved case")
        if args.evidence and args.profile_id is None:
            raise ValueError("--evidence requires resolved case")
        if args.profile_id:
            obj=resolve(data,args.profile_id,args.coast_ms)
            if args.evidence:
                obj=verify_readback(obj,json.loads(args.evidence.read_text()))
        else:
            obj={"schema":data["schema"],"profiles":[p["id"] for p in data["profiles"]],
                 "coast_ms":[s["coast_ms"] for s in data["scenarios"]],
                 "case_count":len(data["profiles"])*len(data["scenarios"]),
                 "simulation_only":True,"firmware_unchanged":True}
        if args.field:
            value=obj[args.field]
            if args.output:
                raise ValueError("Cannot use --output with --field")
            print(value)
        else:
            if args.output:
                args.output.parent.mkdir(parents=True,exist_ok=True)
                args.output.write_text(json.dumps(obj,indent=2,sort_keys=True)+"\\n")
            print(json.dumps(obj,sort_keys=True))
        return 0 if obj.get("source_profile_readback_pass",True) else 1
    except (ValueError,TypeError,KeyError,IndexError,OSError) as exc:
        print("E62_SIM_CASE_PROFILE_FAIL "+str(exc),file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
