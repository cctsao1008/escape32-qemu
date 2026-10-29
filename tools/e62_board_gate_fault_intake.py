#!/usr/bin/env python3
"""Strict bench scope CSV gate-off waveform intake; NO hardware PASS.

The trace must be externally obtained from actual six MOSFET/GaN
GATE-TO-SOURCE differential probes. Raw digital 0/1 inputs are the
scope's *documented/approved* gate activity discriminator; this tool
does not choose Vgs thresholds, fault topology, or numeric latency
acceptance values. Board identity and scope hashes are self-declared
provenance, requiring independent lab corroboration.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import re

GATES=("u_h","u_l","v_h","v_l","w_h","w_l")
FIELDS=("time_ns","fault_active",*GATES)
SOURCES=("nfault","oc_u","oc_v","oc_w")
MANIFEST=("schema","capture_kind","fault_source","board_revision",
          "board_serial","firmware_commit","instrument_id","measured_at_utc",
          "raw_trace_sha256","gate_probe_reference","fault_probe_reference",
          "gate_discriminator_ref","fault_polarity_ref","max_sample_gap_ns",
          "min_pre_fault_ns","min_post_release_ns",
          "approved_max_gate_off_ns")

def positive(v,allow_none=False):
    if allow_none and v is None:return None
    if type(v) is not int or v<=0 or v>=2**31:
        raise ValueError("Missing/invalid explicitly supplied timing bound")
    return v

def verify(raw,meta):
    if set(meta)!=set(MANIFEST) or meta["schema"]!="e62.bench.six-gate-fault.v1":
        raise ValueError("Gate trace manifest schema mismatch")
    if meta["capture_kind"]!="BENCH_VGS_SCOPE_DIGITALIZED_UNVERIFIED" or (
        meta["fault_source"] not in SOURCES):
        raise ValueError("No simulated source or unreviewed fault origin allowed")
    for key in ("board_revision","board_serial","instrument_id",
                "gate_probe_reference","fault_probe_reference",
                "gate_discriminator_ref","fault_polarity_ref"):
        v=meta[key]
        if (not isinstance(v,str) or not v.strip() or
            re.match(r"(?i)^(sim|qemu|mock|unit|fixture):",v)):
            raise ValueError("Incomplete physical six-gate bench provenance: "+key)
    if not isinstance(meta["firmware_commit"],str) or not re.fullmatch(
            r"[a-f0-9]{40}",meta["firmware_commit"]):
        raise ValueError("Actual tested firmware SHA missing")
    if (not isinstance(meta["raw_trace_sha256"],str) or
        not re.fullmatch(r"[a-f0-9]{64}",meta["raw_trace_sha256"]) or
        hashlib.sha256(raw).hexdigest()!=meta["raw_trace_sha256"]):
        raise ValueError("Exact raw Vgs capture SHA mismatch")
    try:
        dt=datetime.fromisoformat(meta["measured_at_utc"].replace("Z","+00:00"))
    except (ValueError,AttributeError) as exc:
        raise ValueError("Invalid scope UTC timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset()!=timezone.utc.utcoffset(dt):
        raise ValueError("Bench trace must have UTC timestamp")
    for k in ("max_sample_gap_ns","min_pre_fault_ns","min_post_release_ns"):
        positive(meta[k])
    positive(meta["approved_max_gate_off_ns"],allow_none=True)

def audit(raw:bytes,manifest:dict):
    verify(raw,manifest)
    try:
        reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")),strict=True)
    except UnicodeDecodeError as exc:
        raise ValueError("Scope capture must be UTF8 CSV") from exc
    if tuple(reader.fieldnames or ())!=FIELDS:
        raise ValueError("Six Vgs activity channels and fault header required")
    rows=[]
    for row in reader:
        if set(row)!=set(FIELDS):
            raise ValueError("Missing scope channel field")
        try:
            t=int(row["time_ns"])
        except (TypeError,ValueError) as exc:
            raise ValueError("Invalid numeric scope time") from exc
        if t<0 or str(t)!=row["time_ns"]:
            raise ValueError("Scope time must be monotonic unsigned nanoseconds")
        flags={}
        for k in ("fault_active",*GATES):
            if row[k] not in ("0","1"):
                raise ValueError("Scope logic discriminator must be exact 0/1")
            flags[k]=int(row[k])
        rows.append((t,flags))
        if len(rows)>250000:
            raise ValueError("Unbounded scope capture")
    if len(rows)<12:
        raise ValueError("Scope capture too short")
    gap_limit=manifest["max_sample_gap_ns"]
    for (t0,_),(t1,_) in zip(rows,rows[1:]):
        if t1<=t0 or t1-t0>gap_limit:
            raise ValueError("Scope sampled clock discontinuity or gap")
    # Exactly one rising fault-active edge, one falling release edge,
    # with observed pre-fault drive and post-release no-rearm window.
    rise=[];fall=[]
    for i in range(1,len(rows)):
        previous=rows[i-1][1]["fault_active"]
        current=rows[i][1]["fault_active"]
        if not previous and current: rise.append(i)
        if previous and not current:fall.append(i)
    if (len(rise)!=1 or len(fall)!=1 or
        not 1<rise[0]<fall[0]<len(rows)-2 or
        rows[0][1]["fault_active"]!=0 or
        rows[-1][1]["fault_active"]!=0):
        raise ValueError("Fault assertion/release not separately observed")
    on,off=rise[0],fall[0]
    tassert=rows[on][0];trelease=rows[off][0]
    if tassert-rows[0][0]<manifest["min_pre_fault_ns"] or (
        rows[-1][0]-trelease<manifest["min_post_release_ns"]):
        raise ValueError("Incomplete powered-pre-fault or released-fault observation")
    if not any(any(flags[g] for g in GATES) for _,flags in rows[:on]):
        raise ValueError("No active six-gate switching before failure")
    # Failure is required while drive remains physically possible,
    # not only after the normal throttle-neutral outputs are off.
    if not any(any(flags[g] for g in GATES)
               for _,flags in rows[max(0,on-3):on+1]):
        raise ValueError("Fault injected only after gate outputs already stopped")
    # Earliest point at which all six gate-to-source channels are low
    # and remain low for EVERY subsequent recorded sample (including
    # after the fault source is released). Any reactivation fails closed.
    last_postfault_active=max(
        (i for i in range(on,len(rows))
         if any(rows[i][1][g] for g in GATES)),default=on-1)
    index=last_postfault_active+1
    if index>=len(rows):
        raise ValueError("Postfault gate reactivation or no six-gate safe-off")
    # Need at least 3 independent all-off samples (avoid 1-point false PASS).
    if len(rows)-index<3 or rows[index][0]>trelease:
        raise ValueError("No persistent six-gate off before fault release")
    # Both the fault assertion edge and final gate disable occurred
    # BETWEEN samples. Never under-report them as exact timestamps.
    # Conservative delay bound: all-off sample minus previous inactive
    # fault sample. The last still-active gate sample yields a lower
    # bound when its timestamp follows the asserted-fault sample.
    observed_upper_ns=rows[index][0]-rows[on-1][0]
    observed_lower_ns=max(0,rows[index-1][0]-tassert) if index>on else 0
    accepted_bound=manifest["approved_max_gate_off_ns"]
    spec_state=("NO_APPROVED_NUMERIC_CRITERION" if accepted_bound is None
                else "CAPTURED_TIMING_UPPER_BOUND_WITHIN_DECLARED_LIMIT"
                if observed_upper_ns<=accepted_bound else
                "CAPTURED_TIMING_LOWER_BOUND_EXCEEDS_DECLARED_LIMIT"
                if observed_lower_ns>accepted_bound else
                "TIMING_INDETERMINATE_AT_SAMPLE_RESOLUTION")
    return {
        "schema":"e62.bench.six-gate-fault-intake-result.v1",
        "fault_source":manifest["fault_source"],
        "raw_capture_sha256":manifest["raw_trace_sha256"],
        "trace_samples":len(rows),
        "fault_assert_sample_ns":tassert,"fault_release_sample_ns":trelease,
        "all_six_vgs_discriminators_off_at_ns":rows[index][0],
        "sampled_gate_off_upper_bound_ns":observed_upper_ns,
        "sampled_gate_off_lower_bound_ns":observed_lower_ns,
        "fault_transition_time_uncertainty_ns":tassert-rows[on-1][0],
        "gate_transition_time_uncertainty_ns":(
            rows[index][0]-rows[index-1][0]),
        "time_resolution_gap_max_ns":max(
            rows[i+1][0]-rows[i][0] for i in range(len(rows)-1)),
        "gate_off_numeric_acceptance":spec_state,
        "capture_no_gate_rearm_through_end":True,
        "actual_silicon_fault_latch_readback_verified":False,
        "actual_driver_input_threshold_verified":False,
        "current_amplifier_transfer_verified":False,
        "scope_discriminator_approval_verified":False,
        "hardware_qualified":False,
        "physical_lab_review":"REQUIRED_RAW_WAVEFORM_AND_PROBE_CALIBRATION",
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
    print("E62_BOARD_GATE_FAULT_INTAKE "+json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
