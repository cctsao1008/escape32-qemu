#!/usr/bin/env python3
"""Independent, SIM_ONLY APC 24x12E *static* torque and J-profile contract.

APC manufacturer model v2022-0915, 2022-09-22:
https://www.apcprop.com/files/PER3_24x12E.dat
No firmware changes; this is an analytical aero source, not a windmill
measurement, nor a calibrated propeller inertia or hardware acceptance.
"""
from __future__ import annotations
import json, math
from pathlib import Path

RPM=(1000,2000,3000,4000,5000,6000)
TORQUE_NM=(0.132,0.494,1.085,1.913,2.996,4.362)
MOTOR_ROTOR_J=0.00013
RATIOS=(1,2,5)
SOURCE_PATH=Path(__file__).resolve().parents[1]/"configs/e62-apc24x12e-47v-study-v1.json"

def static_torque(omega_rad_s:float)->float:
    if type(omega_rad_s) not in (int,float) or not math.isfinite(omega_rad_s):
        raise ValueError("Invalid rotor angular velocity")
    rpm=abs(omega_rad_s)*30.0/math.pi
    if rpm>6000:
        raise ValueError("APC static source outside 0-6000rpm: no extrapolation")
    if rpm<=1000:
        tq=TORQUE_NM[0]*(rpm/1000.0)**2
    else:
        for j in range(1,len(RPM)):
            if rpm<=RPM[j]:
                f=(rpm-RPM[j-1])/(RPM[j]-RPM[j-1])
                tq=TORQUE_NM[j-1]+f*(TORQUE_NM[j]-TORQUE_NM[j-1])
                break
    return math.copysign(tq,omega_rad_s) if omega_rad_s else 0.0

def load(path=SOURCE_PATH):
    raw=Path(path).read_bytes()
    if len(raw)>8192: raise ValueError("Overlarge APC profile")
    d=json.loads(raw)
    expected={
        "schema":"e62.sim.apc24x12e-static-47v.v1",
        "scope":"SIM_ONLY_ANALYTICAL_PROP_NO_FIRMWARE_EDIT",
        "motor_profile":"ecx87-kv210",
        "bus_voltage_v":47,
        "apc_file":"PER3_24x12E.dat",
        "apc_version":"v2022-0915",
        "apc_simulation_date":"2022-09-22",
        "apc_airspeed_mph":0,
        "source_rpm":list(RPM),
        "source_static_torque_nm":list(TORQUE_NM),
        "motor_rotor_inertia_kg_m2":MOTOR_ROTOR_J,
        "effective_total_inertia_ratio_to_motor":list(RATIOS),
        "propeller_inertia_measured":False,
        "source_torque_is_hardware_measurement":False,
        "above_6000rpm_extrapolation":False,
        "original_rel17_p1_criteria_unchanged":True,
        "motor_rearm_permitted_by_profile":False
    }
    if type(d) is not dict or d!=expected or any(type(d[k]) is not type(v) for k,v in expected.items()):
        raise ValueError("Unknown or weakened APC profile")
    return d
