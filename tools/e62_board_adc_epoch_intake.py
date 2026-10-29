#!/usr/bin/env python3
"""Read-only AM13E three-phase ADC *bench-export intake*.

Checks that the actual nine-code housekeeping snapshot source could
be evaluated, not that a windmill/rotor-angle estimator is validated.
A manifest is a claim, NOT authentication of an instrument or board.
All outputs explicitly refuse motor rearm and hardware qualification.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

HEADER=("sample_count","acquisition_tick","completion_tick","read_tick",
        "phase_a","phase_b","phase_c","adc0_eoc","adc1_eoc",
        "adc2_eoc","snapshot_coherent","six_gate_off","trip_clear",
        "trigger_overruns")
MANIFEST=("schema","capture_kind","board_revision","board_serial",
          "firmware_commit","instrument_id","measured_at_utc",
          "trace_sha256","phase_pinmap_ref","adc_calibration_ref",
          "sample_clock_ref","tick_hz","max_scan_ticks","max_gap_ticks",
          "max_age_ticks","max_rank_hold_ticks","min_adjacent_codes")
SECTOR=((0,1,2),(0,2,1),(2,0,1),(2,1,0),(1,2,0),(1,0,2))
U32=2**32
MAX_CSV_BYTES=24*1024*1024  # Defensive bound for up to 200,000 scan rows.

def strict_int(x,minimum=0,maximum=U32-1):
    if type(x) is int:
        n=x
    elif isinstance(x,str) and re.fullmatch(r"(?:0|[1-9][0-9]*)",x):
        n=int(x)
    else:
        raise ValueError("Noncanonical unsigned integer")
    if not minimum<=n<=maximum:
        raise ValueError("Unsigned integer out of board trace range")
    return n

def metadata(raw, manifest):
    if not isinstance(manifest,dict):
        raise ValueError("ADC manifest must be a JSON object")
    if set(manifest)!=set(MANIFEST) or manifest["schema"]!="e62.bench.adc-epoch.v1":
        raise ValueError("ADC manifest schema mismatch")
    if manifest["capture_kind"]!="BENCH_CAPTURE_DECLARED_UNVERIFIED":
        raise ValueError("No synthetic model or automatic hardware approval permitted")
    for name in ("board_revision","board_serial","instrument_id",
                 "phase_pinmap_ref","adc_calibration_ref","sample_clock_ref"):
        v=manifest[name]
        if (not isinstance(v,str) or not v.strip() or
            re.match(r"(?i)^(qemu|sim|mock|unit|fixture):",v.strip())):
            raise ValueError("Missing physical acquisition provenance: "+name)
    if not isinstance(manifest["firmware_commit"],str) or not re.fullmatch(
            "[a-f0-9]{40}",manifest["firmware_commit"]):
        raise ValueError("Actual firmware commit missing")
    if (not isinstance(manifest["trace_sha256"],str) or
        not re.fullmatch("[0-9a-f]{64}",manifest["trace_sha256"]) or
        hashlib.sha256(raw).hexdigest()!=manifest["trace_sha256"]):
        raise ValueError("Raw ADC trace SHA256 mismatch")
    try:
        dt=datetime.fromisoformat(manifest["measured_at_utc"].replace("Z","+00:00"))
    except (ValueError,AttributeError) as exc:
        raise ValueError("Bad capture UTC timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset()!=timezone.utc.utcoffset(dt):
        raise ValueError("ADC bench timestamp must be UTC")
    for field in ("tick_hz","max_scan_ticks","max_gap_ticks",
                  "max_age_ticks","max_rank_hold_ticks","min_adjacent_codes"):
        if type(manifest[field]) is not int:
            raise ValueError("ADC board timing budget must be a JSON integer: "+field)
        strict_int(manifest[field],1)
    if (strict_int(manifest["tick_hz"])>100_000_000 or
        strict_int(manifest["min_adjacent_codes"])>4095 or
        any(strict_int(manifest[x])>=2**31 for x in
            ("max_scan_ticks","max_gap_ticks","max_age_ticks","max_rank_hold_ticks"))):
        raise ValueError("Unbounded board timestamp/ADC contract")

def audit(raw:bytes, manifest:dict):
    metadata(raw,manifest)
    if len(raw)>MAX_CSV_BYTES:
        raise ValueError("ADC trace exceeds bounded CSV intake size")
    try:
        content=raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("ADC trace must be UTF8 CSV") from exc
    import io
    reader=csv.DictReader(io.StringIO(content),strict=True)
    if tuple(reader.fieldnames or ())!=HEADER:
        raise ValueError("ADC epoch fields/header mismatch")
    rows=list(reader)
    if not 4<=len(rows)<=200000:
        raise ValueError("ADC trace missing or excessive epochs")
    prev_id=prev_end=prev_read=prev_overruns=None
    prev_rank=last_rank_tick=rank_dir=None
    transitions=skips=low_contrast=0
    min_delta= strict_int(manifest["min_adjacent_codes"])
    max_scan=max_gap=max_age=0
    for row in rows:
        if set(row)!=set(HEADER):
            raise ValueError("Incomplete ADC CSV record")
        x={k:strict_int(v,0,4095 if k in ("phase_a","phase_b","phase_c") else U32-1)
           for k,v in row.items()}
        for key in ("adc0_eoc","adc1_eoc","adc2_eoc","snapshot_coherent",
                    "six_gate_off","trip_clear"):
            if x[key]!=1:
                raise ValueError("ADC incomplete/unsafe sample: "+key)
        if x["sample_count"]==0:
            raise ValueError("ADC snapshot identity zero")
        if prev_id is not None and x["sample_count"]!=(prev_id+1)%U32:
            raise ValueError("Lost/repeated ADC epoch")
        if prev_overruns is not None and x["trigger_overruns"]!=prev_overruns:
            raise ValueError("ADC trigger overrun changed within observation")
        scan=(x["completion_tick"]-x["acquisition_tick"])%U32
        age=(x["read_tick"]-x["completion_tick"])%U32
        total=(x["read_tick"]-x["acquisition_tick"])%U32
        if (scan>manifest["max_scan_ticks"] or
            age>manifest["max_age_ticks"] or
            total>manifest["max_age_ticks"]):
            raise ValueError("ADC scan/staleness violates declared board budget")
        max_scan=max(max_scan,scan); max_age=max(max_age,total)
        if prev_read is not None:
            # The PendSV housekeeping exporter owns one completed and
            # consumed snapshot before initiating the next acquisition.
            # Modulo subtraction admits genuine uint32 wrap but rejects
            # an overlapping/reordered acquisition as a huge backward gap.
            after_read=(x["acquisition_tick"]-prev_read)%U32
            if after_read>manifest["max_gap_ticks"]:
                raise ValueError("ADC overlapping or reordered snapshot epochs")
        if prev_end is not None:
            gap=(x["completion_tick"]-prev_end)%U32
            if gap==0 or gap>manifest["max_gap_ticks"]:
                raise ValueError("ADC cadence/gap violates board budget")
            max_gap=max(max_gap,gap)
        volts=(x["phase_a"],x["phase_b"],x["phase_c"])
        order=tuple(sorted(range(3),key=lambda i:-volts[i]))
        d1=volts[order[0]]-volts[order[1]]
        d2=volts[order[1]]-volts[order[2]]
        if min(d1,d2)<min_delta:
            low_contrast+=1
            # A missing qualified phase rank interrupts the continuity chain.
            prev_rank=last_rank_tick=rank_dir=None
        else:
            rank=SECTOR.index(order)
            if prev_rank is not None:
                hold=(x["completion_tick"]-last_rank_tick)%U32
                if hold>manifest["max_rank_hold_ticks"]:
                    skips+=1
                    prev_rank=last_rank_tick=rank_dir=None
                else:
                    delta=(rank-prev_rank)%6
                    if delta!=0:
                        direction=1 if delta==1 else -1 if delta==5 else 0
                        if not direction or (rank_dir is not None and
                                             direction!=rank_dir):
                            skips+=1
                            prev_rank=last_rank_tick=rank_dir=None
                        else:
                            transitions+=1
                            rank_dir=direction
                            last_rank_tick=x["completion_tick"]
            if prev_rank is None:
                last_rank_tick=x["completion_tick"]
            prev_rank=rank
        prev_id=x["sample_count"];prev_end=x["completion_tick"]
        prev_read=x["read_tick"]
        prev_overruns=x["trigger_overruns"]
    return {
        "schema":"e62.bench.adc-epoch-intake-result.v1",
        "capture_declared":manifest["capture_kind"],
        "trace_sha256":manifest["trace_sha256"],
        "epochs_checked":len(rows),"timebase_hz_declared":manifest["tick_hz"],
        "max_observed_scan_ticks":max_scan,
        "max_observed_inter_epoch_gap_ticks":max_gap,
        "max_observed_age_ticks":max_age,
        "ambiguous_low_code_contrast_epochs":low_contrast,
        "adjacent_phase_rank_transitions_only":transitions,
        "unreliable_or_skipped_rank_events":skips,
        "interpretation":("INCOMPLETE_OR_AMBIGUOUS_PHASE_RANK_EVIDENCE"
                          if skips or low_contrast else
                          "NO_RANK_CONTRADICTION_IN_SUBMITTED_SAMPLE_ONLY"),
        "acquisition_timebase_on_real_silicon_verified":False,
        "inter_adc_channel_skew_verified":False,
        "physical_rotor_direction_or_angle_qualified":False,
        "motor_rearm_permitted":False,
        "hardware_qualified":False,
        "physical_review":"REQUIRED_EXTERNAL_TO_THIS_TOOL",
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
    print("E62_BOARD_ADC_EPOCH_INTAKE "+json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
