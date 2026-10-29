#!/usr/bin/env python3
"""E62 three-phase physical current-sense calibration CSV intake.

COMPUTATION ONLY. A source-asserted real current instrument AND board
schematic are needed to confirm the gain polarity, common-mode headroom,
ADC Vref, shunt, amplifier, comparator DAC and three phase pin mapping.
Regression data cannot program hardware, select an OCP limit or certify
any 50A/80A customer requirement. External lab review remains mandatory.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime,timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re

COLUMNS=("phase","point_id","reference_current_ma","adc_raw_code")
PHASES=("U","V","W")
MANIFEST=("schema","capture_kind","board_revision","board_serial",
          "firmware_commit","measured_at_utc","reference_instrument_id",
          "adc_instrument_id","raw_trace_sha256","current_probe_cal_ref",
          "adc_reference_cal_ref","shunt_amplifier_schematic_ref",
          "adc_phase_route_ref","hardware_excitation_method",
          "transfer_topology")

def _meta(raw,meta):
    if set(meta)!=set(MANIFEST) or meta["schema"]!="e62.bench.current-transfer.v1":
        raise ValueError("Current-sense transfer manifest schema mismatch")
    if (meta["capture_kind"]!="BENCH_INDEPENDENT_CURRENT_REFERENCE_UNVERIFIED" or
        meta["hardware_excitation_method"]!="LOW_ENERGY_NO_PROPELLER"):
        raise ValueError("Current calibration cannot borrow synthetic motor data")
    if meta["transfer_topology"] not in ("SIGNED_LINEAR","ABSOLUTE_LINEAR"):
        raise ValueError("Transfer topology not explicitly selected")
    for k in ("board_revision","board_serial","reference_instrument_id",
              "adc_instrument_id","current_probe_cal_ref",
              "adc_reference_cal_ref","shunt_amplifier_schematic_ref",
              "adc_phase_route_ref"):
        v=meta[k]
        if (not isinstance(v,str) or not v.strip() or
            re.match(r"(?i)^(qemu|sim|mock|unit|fixture):",v.strip())):
            raise ValueError("Missing independently evidenced current calibration: "+k)
    if not isinstance(meta["firmware_commit"],str) or not re.fullmatch(
            "[a-f0-9]{40}",meta["firmware_commit"]):
        raise ValueError("Actual board firmware SHA missing")
    if (not isinstance(meta["raw_trace_sha256"],str) or
        not re.fullmatch("[0-9a-f]{64}",meta["raw_trace_sha256"]) or
        hashlib.sha256(raw).hexdigest()!=meta["raw_trace_sha256"]):
        raise ValueError("Current reference raw trace SHA256 mismatch")
    try:
        dt=datetime.fromisoformat(meta["measured_at_utc"].replace("Z","+00:00"))
    except (ValueError,AttributeError) as exc:
        raise ValueError("Invalid bench calibration UTC timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset()!=timezone.utc.utcoffset(dt):
        raise ValueError("Independent current reference capture must be UTC")

def _int(s,allow_negative=False):
    if not isinstance(s,str) or not re.fullmatch(
            r"-?(?:0|[1-9][0-9]*)" if allow_negative else
            r"(?:0|[1-9][0-9]*)",s):
        raise ValueError("Noncanonical signed current / unsigned ADC code")
    return int(s)

def audit(raw:bytes,meta:dict):
    _meta(raw,meta)
    try:
        reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")),strict=True)
    except UnicodeDecodeError as exc:
        raise ValueError("Current ADC CSV must be UTF8") from exc
    if tuple(reader.fieldnames or ())!=COLUMNS:
        raise ValueError("Signed reference current and ADC code header required")
    by_phase={p:[] for p in PHASES};ids=set()
    for row in reader:
        if set(row)!=set(COLUMNS) or row["phase"] not in PHASES:
            raise ValueError("Unknown or missing current phase mapping")
        key=(row["phase"],row["point_id"])
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}",row["point_id"] or "") or key in ids:
            raise ValueError("Missing/duplicate reference current sweep point ID")
        ids.add(key)
        ma=_int(row["reference_current_ma"],allow_negative=True)
        code=_int(row["adc_raw_code"])
        if abs(ma)>500000 or not 1<=code<=4094:
            raise ValueError("Current or ADC code invalid/saturated")
        by_phase[row["phase"]].append((ma,code))
        if len(ids)>20000:raise ValueError("Unbounded board current calibration data")
    result={}
    for phase,samples in by_phase.items():
        currents=[x for x,_ in samples]
        if (len(samples)<7 or len(set(currents))<5 or
            not any(x<0 for x in currents) or not any(x>0 for x in currents) or
            not any(x==0 for x in currents)):
            raise ValueError("Missing zero and both current polarities: "+phase)
        x=[(abs(v) if meta["transfer_topology"]=="ABSOLUTE_LINEAR" else v)/1000.
           for v in currents]
        if len(set(x))<3:
            raise ValueError("Excitation amplitudes not independently spaced: "+phase)
        y=[float(code) for _,code in samples]
        avg_x=sum(x)/len(x);avg_y=sum(y)/len(y)
        sxx=sum((q-avg_x)**2 for q in x)
        if sxx<=0:raise ValueError("Zero calibration current variance")
        slope=sum((q-avg_x)*(code-avg_y) for q,code in zip(x,y))/sxx
        intercept=avg_y-slope*avg_x
        residual=[a-(intercept+slope*b) for a,b in zip(y,x)]
        rms=math.sqrt(sum(z*z for z in residual)/len(residual))
        if (not all(map(math.isfinite,(slope,intercept,rms))) or
            abs(slope)<1e-9):
            raise ValueError("Unidentifiable current amplifier transfer")
        result[phase]={
            "source_points":len(samples),
            "external_reference_current_min_a":min(currents)/1000.,
            "external_reference_current_max_a":max(currents)/1000.,
            "candidate_adc_offset_code":intercept,
            "candidate_gain_adc_codes_per_amp":slope,
            "candidate_max_abs_residual_adc_codes":max(map(abs,residual)),
            "candidate_rms_residual_adc_codes":rms,
            "clipping_samples_rejected":True,
            "adc_mux_mapping_silicon_verified":False,
            "current_shunt_and_amplifier_qualified":False,
        }
    return {
        "schema":"e62.bench.current-transfer-intake-result.v1",
        "trace_sha256":meta["raw_trace_sha256"],
        "transfer_topology_declared":meta["transfer_topology"],
        "channels":result,
        "candidate_gain_is_not_calibrated_hardware":True,
        "motor_generated_oc_qualified":False,
        "comparator_dac_trip_current_qualified":False,
        "current_limit_autoconfig_permitted":False,
        "hardware_qualified":False,
        "physical_lab_review":"REQUIRED_INDEPENDENT_SOURCE_AND_ANALOG_PATH",
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--csv",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    result=audit(a.csv.read_bytes(),json.loads(a.manifest.read_text()))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("E62_BOARD_CURRENT_TRANSFER_INTAKE "+json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
