#!/usr/bin/env python3
"""Read-only E62 simulated rotor-state/initial-torque audit after a coast.

This diagnostic observes the QEMU *model-internal* electrical angle and
mechanical torque from E62_P0_EVENT ROTOR. It never supplies those fields to
the Guest, never enables firmware angle sensing, and does not override the
unchanged strict Original P1 or independent second-demand oracle.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p1_qualification import commands_for_scenario

EVENT = re.compile(
    r"\bE62_P0_EVENT seq=(\d+) vns=(\d+) kind=([A-Z0-9_]+)"
    r" a=(-?\d+) b=(-?\d+) c=(-?\d+) d=(-?\d+) e=(-?\d+) f=(-?\d+)\b"
)

def read_events(path: Path):
    records = []
    previous_seq = 0
    previous_vns = -1
    for line in path.open(errors="replace"):
        m = EVENT.search(line)
        if not m:
            continue
        seq, vns = int(m[1]), int(m[2])
        if seq != previous_seq + 1 or vns < previous_vns:
            raise ValueError("Native source events not sequential/monotonic")
        previous_seq, previous_vns = seq, vns
        records.append({"vns":vns,"kind":m[3],
                        "data":tuple(int(m[i]) for i in range(4,10))})
    if not records:
        raise ValueError("No authentic native E62_P0_EVENT records")
    return records

def diagnose(events, scenario):
    if scenario.get("schema")!="e62.native.dshot.v1" or (
        scenario.get("protocol")!="DSHOT600" or
        scenario.get("frame_period_ns")!=1_000_000 or
        scenario.get("guest_ready_gating") is not False):
        raise ValueError("Unexpected source-owned DShot scenario")
    stages=scenario.get("stages",[])
    if (len(stages)!=5 or
        [s.get("permille") for s in stages]!=[0,200,0,200,0] or
        any(s.get("kind")!="hold" or
            not isinstance(s.get("duration_ms"),int) or
            s["duration_ms"]<300 for s in stages)):
        raise ValueError("Unexpected five-stage second-demand policy")
    ds=[e for e in events if e["kind"]=="DSHOT"]
    expected_count=sum(s["duration_ms"] for s in stages)
    if len(ds)!=expected_count:
        raise ValueError("Incomplete DShot frame source")
    borders=[0]
    for s in stages:
        borders.append(borders[-1]+s["duration_ms"])
    # E62_P0_EVENT DSHOT.c is the encoded DShot command (e.g.
    # 200-permille -> 448), NOT permille. Reuse the existing strict P1
    # source decoder rather than invent an alternate throttle mapping.
    commands=list(commands_for_scenario([
        (item["duration_ms"],item["permille"],item["permille"],1)
        for item in stages]))
    if len(commands)!=len(ds):
        raise ValueError("Invalid canonical strict P1 DShot command count")
    for i,e in enumerate(ds):
        expected_stage, expected_encoded_command=commands[i]
        if e["data"][0]!=i or e["data"][1]!=expected_stage:
            raise ValueError("Wrong source-owned frame/stage")
        if e["data"][2]!=expected_encoded_command:
            raise ValueError("Unexpected DShot encoded source command")
        if i>=2 and abs((e["vns"]-ds[i-1]["vns"])-1_000_000)>100:
            raise ValueError("DSHOT source clock discontinuity")
    stage3_start=ds[borders[3]]["vns"]
    prior=[e for e in events if e["kind"]=="ROTOR" and
           e["vns"]<stage3_start]
    next_20=[e for e in events if e["kind"]=="ROTOR" and
             stage3_start<=e["vns"]<stage3_start+20_000_000]
    if not prior or len(next_20)<10:
        raise ValueError("Not enough native physical rotor records around restart")
    before=prior[-1]
    first=next_20[0]
    angle_deg=(math.degrees(before["data"][1]/1000.0)%360.0)
    torques=[e["data"][5]/1e6 for e in next_20]
    rpm=[e["data"][0]/1000.0 for e in next_20]
    future=[e["vns"] for e in events if e["kind"]=="CAP1_ACK" and
            e["vns"]>=stage3_start]
    first_capture_delay_ms=(
        (future[0]-stage3_start)/1e6 if future else None)
    return {
        "schema":"e62.experimental.native-coast-phase-torque-audit.v1",
        "classification":"SIM_ONLY_READ_ONLY_PLANT_DIAGNOSTIC_NOT_GUEST_ROTOR_SENSING",
        "p1_qualified":False,
        "hardware_qualified":False,
        "has_guest_rotor_angle_measurement":False,
        "source_dshot_frames":len(ds),
        "coast_duration_ms":stages[2]["duration_ms"],
        "second_demand_start_virtual_ns":stage3_start,
        "pre_demand_rpm":before["data"][0]/1000.0,
        "pre_demand_unwrapped_electrical_angle_mrad":before["data"][1],
        "pre_demand_wrapped_electrical_angle_deg":round(angle_deg,6),
        "first_post_demand_sample_ms":round(
            (first["vns"]-stage3_start)/1e6,6),
        "first_post_demand_model_torque_nm":torques[0],
        "first_post_demand_model_torque_negative":torques[0]<0,
        "first_20ms_min_model_torque_nm":min(torques),
        "first_20ms_min_rpm":min(rpm),
        "first_20ms_negative_rpm_samples_le_minus50":sum(v<=-50 for v in rpm),
        "first_new_guest_cap1_ack_ms":first_capture_delay_ms,
        "rotor_model_samples_first_20ms":len(next_20),
        "do_not_use_angle_or_torque_as_guest_input":True,
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--scenario",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    result=diagnose(read_events(a.events),
                    json.loads(a.scenario.read_text()))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print("E62_RESTART_PHASE_TORQUE_AUDIT "+json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
