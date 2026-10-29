#!/usr/bin/env python3
"""E62 source-owned *passive* BEMF quantization audit before restart.

The only signal observed is the model's three ADC-like BEMF_FRONTEND
codes. No QEMU rotor angle, speed, torque or internal theta is read or
passed to the firmware. This is NOT proof of an actual board ADC route;
a positive contrast reading is NEVER treated as rotor phase qualification.

The 3-LSB illustrative diagnostic contrast floor is NOT a production
ADC-noise or standstill/windmill-detection requirement. It is explicitly
greater than a single-code ambiguity. Passing this floor alone does NOT
mean the rotor angle/direction is observable.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.e62_restart_phase_torque_audit import read_events
from tools.native_p1_qualification import commands_for_scenario

WINDOW_NS = 100_000_000
COAST_SETTLE_NS = 200_000_000
MIN_SOURCE_SAMPLES = 80
DIAGNOSTIC_CONTRAST_FLOOR_CODES = 3

def evaluate(events, scenario):
    if (scenario.get("schema")!="e62.native.dshot.v1" or
            scenario.get("protocol")!="DSHOT600" or
            scenario.get("frame_period_ns")!=1_000_000 or
            scenario.get("guest_ready_gating") is not False):
        raise ValueError("Unexpected source DShot schema or timing")
    stages=scenario.get("stages", [])
    if (len(stages)!=5 or
        [s.get("permille") for s in stages]!=[0,200,0,200,0] or
        any(s.get("kind")!="hold" or
            not isinstance(s.get("duration_ms"),int) or
            s["duration_ms"]<300 for s in stages)):
        raise ValueError("Unexpected neutral/coast/restart scenario")
    n=sum(s["duration_ms"] for s in stages)
    ds=[e for e in events if e["kind"]=="DSHOT"]
    if len(ds)!=n:
        raise ValueError("Incomplete real source-owned DShot frames")
    expected=commands_for_scenario([
        (s["duration_ms"],s["permille"],s["permille"],1)
        for s in stages])
    borders=[0]
    for stage in stages:
        borders.append(borders[-1]+stage["duration_ms"])
    for idx,(e,(stage,command)) in enumerate(zip(ds,expected)):
        if e["data"][:5]!=(idx,stage,command,0,0):
            raise ValueError("Source DShot stage, index or encoded command changed")
        if idx>=2 and abs(e["vns"]-ds[idx-1]["vns"]-1_000_000)>100:
            raise ValueError("Source DShot 1kHz clock drift")
    coast_start=ds[borders[2]]["vns"]
    restart=ds[borders[3]]["vns"]
    window_start=restart-WINDOW_NS
    if window_start<coast_start+COAST_SETTLE_NS:
        raise ValueError("Not enough settled neutral before restart")
    coast_active=[e for e in events if
        coast_start+COAST_SETTLE_NS<=e["vns"]<restart and
        e["kind"] in ("PWM_PAIR","CAP1_ACK","TIMG12_ACK")]
    if coast_active:
        raise ValueError("Coast still carries active guest motor events")
    samples=[e for e in events if e["kind"]=="BEMF_FRONTEND" and
             window_start<=e["vns"]<restart]
    if len(samples)<MIN_SOURCE_SAMPLES or len(samples)>130:
        raise ValueError("Missing/duplicated phase-voltage source window")
    if samples[0]["vns"]>window_start+2_000_000 or (
            samples[-1]["vns"]<restart-3_000_000):
        raise ValueError("Phase-voltage source window incomplete")
    contrasts=[]
    phase=[[],[],[]]
    comparator=[]
    for e in samples:
        values=e["data"][:3]
        if len(values)!=3 or any(type(v) is not int or v<0 or v>4095
                                  for v in values):
            raise ValueError("Invalid three phase BEMF ADC code")
        for p in range(3):
            phase[p].append(values[p])
        contrasts.append(max(values)-min(values))
        comparator.append(e["data"][5])
    # Pure source-owned model diagnostic: 50ms windows at the start
    # of neutral capture the rapid disappearance of phase-code contrast.
    # These are NOT proof of rotor direction or a calibrated ADC route.
    decay=[]
    for interval_ms in range(0,300,50):
        begin=coast_start+interval_ms*1_000_000
        finish=begin+50_000_000
        window=[e for e in events if
            e["kind"]=="BEMF_FRONTEND" and begin<=e["vns"]<finish]
        if len(window)<35 or len(window)>65:
            raise ValueError("Incomplete native 50ms coast source window")
        code_contrast=[max(e["data"][:3])-min(e["data"][:3])
                       for e in window]
        if any(v<0 or v>4095 for e in window for v in e["data"][:3]):
            raise ValueError("Invalid native coast BEMF quantization")
        decay.append({"neutral_age_start_ms":interval_ms,
                      "neutral_age_end_ms":interval_ms+50,
                      "sample_count":len(window),
                      "max_phase_code_contrast":max(code_contrast),
                      "min_phase_code_contrast":min(code_contrast)})
    spans=[max(p)-min(p) for p in phase]
    max_contrast=max(contrasts)
    # A model BEMF array is source-only telemetry, not a firmware
    # ADC sample. Do NOT permit this diagnostic to arm/drive the Guest.
    insufficient=max_contrast<DIAGNOSTIC_CONTRAST_FLOOR_CODES
    return {
        "schema":"e62.experimental.passive-bemf-quantization-audit.v1",
        "classification":("INSUFFICIENT_MODEL_BEMF_CODE_CONTRAST"
                         if insufficient else
                         "SOME_MODEL_CODE_CONTRAST_DIRECTION_STILL_UNQUALIFIED"),
        "passive_model_signal_qualified_for_rotor_angle":False,
        "board_ADC_route_qualified":False,
        "guest_has_rotor_angle_measurement":False,
        "firmware_enable_granted":False,
        "hardware_qualified":False,
        "source_frozen":True,
        "diagnostic_contrast_floor_codes":DIAGNOSTIC_CONTRAST_FLOOR_CODES,
        "diagnostic_floor_not_product_threshold":True,
        "coast_duration_ms":stages[2]["duration_ms"],
        "window_length_ms":WINDOW_NS//1_000_000,
        "source_frames":len(ds),
        "source_bemf_samples":len(samples),
        "max_instantaneous_phase_to_phase_code_contrast":max_contrast,
        "max_phase_code_temporal_span":max(spans),
        "per_phase_code_temporal_spans":spans,
        "min_max_per_phase":[[min(p),max(p)] for p in phase],
        "phase_contrast_histogram":dict(Counter(contrasts)),
        "first_300ms_passive_coast_decay_50ms_buckets":decay,
        "number_of_postsettle_active_motor_events":len(coast_active),
        "comment":"Without an authenticated board ADC route and reliable phase-order edges, quantized model codes cannot establish a safe windmill restart sector."
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--scenario",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    result=evaluate(read_events(a.events),json.loads(a.scenario.read_text()))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print("E62_PASSIVE_BEMF_COAST_OBSERVABILITY "+json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
