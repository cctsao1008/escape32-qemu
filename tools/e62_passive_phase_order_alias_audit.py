#!/usr/bin/env python3
"""Read-only 1kHz passive phase-order observability: FAIL CLOSED on skipped sectors.

Model-only BEMF_FRONTEND (three ADC-like phase codes) + independent external
source DShot timestamps; NO model theta, rotor RPM, torque, GPIO/Guest writes.
A ranked six-sector phase-voltage permutation is NOT a qualified real rotor
electrical angle, direction or board sample. Comparator/pinmux calibration
is not inferred. Code floors below are DIAGNOSTIC, not product limits.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.e62_restart_phase_torque_audit import read_events
from tools.native_p1_qualification import commands_for_scenario

SECTOR_ORDER=((0,1,2),(0,2,1),(2,0,1),(2,1,0),(1,2,0),(1,0,2))
REQUIRED_ADJACENT_CODES=2
EARLY_WINDOW_NS=100_000_000

def audit(events,scenario):
    stages=scenario.get("stages",[])
    if (scenario.get("schema")!="e62.native.dshot.v1" or
        scenario.get("protocol")!="DSHOT600" or
        scenario.get("frame_period_ns")!=1_000_000 or
        scenario.get("guest_ready_gating") is not False or len(stages)!=5 or
        [s.get("permille") for s in stages]!=[0,200,0,200,0] or
        any(s.get("kind")!="hold" or
            not isinstance(s.get("duration_ms"),int) or
            s["duration_ms"]<300 for s in stages)):
        raise ValueError("Unrecognized immutable source demand/coast stages")
    ds=[e for e in events if e["kind"]=="DSHOT"]
    exp=list(commands_for_scenario([(s["duration_ms"],s["permille"],
                                    s["permille"],1) for s in stages]))
    if len(ds)!=len(exp) or any(e["data"][:5]!=(i,st,command,0,0)
        for i,(e,(st,command)) in enumerate(zip(ds,exp))):
        raise ValueError("DShot source frame count/order/value mismatch")
    # As in the prior pinned source auditor, the FIRST frame is an
    # explicit bootstrap/onset marker. The first-to-second interval is
    # not a steady-state 1ms frame period (measured 855012ns); all later
    # source intervals must remain within 100ns of real 1kHz cadence.
    if any(abs(ds[i]["vns"]-ds[i-1]["vns"]-1_000_000)>100
           for i in range(2,len(ds))):
        raise ValueError("DShot source clock is not 1kHz")
    coast_start=ds[stages[0]["duration_ms"]+stages[1]["duration_ms"]]["vns"]
    samples=[e for e in events if e["kind"]=="BEMF_FRONTEND" and
             coast_start<=e["vns"]<coast_start+EARLY_WINDOW_NS]
    if not 90<=len(samples)<=105:
        raise ValueError("Missing or duplicated source BEMF early-coast window")
    # This is the model's 1kHz read-only diagnostic journal, NOT the
    # Guest ADC clock. Stale/duplicated timestamps cannot be used even
    # for a diagnostic phase-rank ordering claim.
    if (samples[0]["vns"]>coast_start+2_000_000 or
        samples[-1]["vns"]<coast_start+EARLY_WINDOW_NS-3_000_000 or
        any(not 900_000<=curr["vns"]-prior["vns"]<=1_100_000
            for prior,curr in zip(samples,samples[1:]))):
        raise ValueError("Stale, missing or aliased model BEMF diagnostic timestamps")
    seq=[]
    for e in samples:
        volts=e["data"][:3]
        if any(type(v) is not int or v<0 or v>4095 for v in volts):
            raise ValueError("Invalid source phase voltage ADC-like code")
        ranking=tuple(sorted(range(3),key=lambda i:-volts[i]))
        levels=[volts[i] for i in ranking]
        if (levels[0]-levels[1] < REQUIRED_ADJACENT_CODES or
            levels[1]-levels[2] < REQUIRED_ADJACENT_CODES):
            continue
        state=SECTOR_ORDER.index(ranking)
        if not seq or state!=seq[-1][1]:
            seq.append((e["vns"],state))
    transitions=[(curr[1]-prior[1])%6 for prior,curr in zip(seq,seq[1:])]
    skipped=sum(x in (2,3,4) for x in transitions)
    reversed_count= min(transitions.count(1),transitions.count(5))
    return {
        "schema":"e62.experimental.native-passive-phase-order-alias-audit.v1",
        "classification":("PHASE_SECTOR_SKIPS_UNOBSERVABLE" if skipped
                          else "NO_SKIPS_SEEN_STILL_UNQUALIFIED"),
        "early_coast_window_ms":100,
        "minimum_adjacent_phase_code_separation":REQUIRED_ADJACENT_CODES,
        "threshold_is_not_board_ADC_noise_calibration":True,
        "raw_bemf_source_samples":len(samples),
        "distinct_observable_six_permutation_states":len(seq),
        "observed_rank_transitions":len(transitions),
        "adjacent_up_transition_count":transitions.count(1),
        "adjacent_down_transition_count":transitions.count(5),
        "skipped_or_ambiguous_sector_transitions":skipped,
        "mixed_direction_indicators":reversed_count,
        "native_guest_rearm_permitted":False,
        "qualified_physical_rotor_phase":False,
        "qualified_physical_rotor_direction":False,
        "board_ADC_sample_timing_qualified":False,
        "read_model_rotor_angle_speed_or_torque":False,
        "hardware_qualified":False,
        "original_P1_qualified":False,
        "comment":"Ranked ADC-like voltage phases are source-model only. Skipped ranked sectors may indicate phase aliasing/uncertain sampling, not a unique physical rotor speed or calibrated angle."
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--scenario",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    x=audit(read_events(a.events),json.loads(a.scenario.read_text()))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(x,sort_keys=True,indent=2)+"\n")
    print("E62_PASSIVE_PHASE_ORDER_ALIAS "+json.dumps(x,sort_keys=True))

if __name__=="__main__":
    main()
