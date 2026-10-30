#!/usr/bin/env python3
"""E62 #5 independently audit Original Guest's REAL ADCRESULT read epochs.

The source is native QEMU Guest-triggered ADC_PHASE_EOC and
ADC_PHASE_READ, NOT the BEMF_FRONTEND 1kHz diagnostic journal, QEMU theta,
RPM, or torque. Diagnostic six-ranked-code contrast alone NEVER grants
direction, rotor angle, motor rearm, or a first/second demand PASS.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_dshot_scenario import load_native_scenario
from tools.native_p1_qualification import commands_for_scenario
from tools.e62_restart_phase_torque_audit import read_events

PHASE_SOC=((0,1,12),(1,2,2),(2,1,5))
EARLY_NS=100_000_000
LAST_NS=100_000_000
MAX_EOC_READ_NS=5_000_000
MAX_THREE_PHASE_SKEW_NS=5_000_000
MIN_WINDOW_EPOCHS=40
DIAGNOSTIC_CODE_CONTRAST_FLOOR=3
# Rank traversal is a waveform diagnostic. Even an apparently clean
# series cannot prove actual electrical angle or authorize Guest rearm.
RANK_SEQUENCE=((0,1,2),(0,2,1),(2,0,1),(2,1,0),(1,2,0),(1,0,2))

RANK_PROFILE_PATH=Path(__file__).resolve().parents[1]/"configs/e62-guest-adc-phase-rank-v1.json"

def load_rank_profile(path=RANK_PROFILE_PATH):
    d=json.loads(Path(path).read_text())
    expected={
        "schema":"e62.sim.guest-adc-phase-rank-confidence.v1",
        "scope":"SIM_ONLY_GUEST_ADC_DIAGNOSTIC_NEVER_REARM",
        "minimum_adjacent_phase_code_separation":3,
        "minimum_valid_rank_fraction":0.75,
        "maximum_valid_rank_sample_gap_ms":5,
        "minimum_one_way_rank_transitions":3,
        "rearm_permitted":False,
        "rotor_angle_qualified":False
    }
    if (type(d) is not dict or d!=expected or
        any(type(d[k]) is not type(v) for k,v in expected.items())):
        raise ValueError("Unsafe or unversioned Guest ADC phase-rank profile")
    return d

def rank_motion_diagnostic(triplets, separation=3,
                           minimum_valid_fraction=0.75,
                           maximum_valid_gap_ns=5_000_000,
                           minimum_one_way_transitions=3):
    if (type(separation) is not int or not 3<=separation<=16 or
        type(minimum_valid_fraction) not in (int,float) or
        not 0.75<=minimum_valid_fraction<=1.0 or
        type(maximum_valid_gap_ns) is not int or
        not 1_000_000<=maximum_valid_gap_ns<=5_000_000 or
        type(minimum_one_way_transitions) is not int or
        minimum_one_way_transitions<3):
        raise ValueError("Unsafe uncalibrated Guest phase rank confidence floor")
    states=[]
    usable=[]
    rejected_ties=0
    previous_ns=-1
    for item in triplets:
        when=item["vns"]
        volts=item["codes"]
        if (type(when) is not int or when<=previous_ns or
            len(volts)!=3 or any(type(x) is not int or not 0<=x<=4095
                                 for x in volts)):
            raise ValueError("Invalid or stale Guest ADC triplet")
        previous_ns=when
        order=tuple(sorted(range(3),key=lambda i:-volts[i]))
        if (volts[order[0]]-volts[order[1]]<separation or
            volts[order[1]]-volts[order[2]]<separation):
            rejected_ties+=1
            continue
        usable.append(when)
        state=RANK_SEQUENCE.index(order)
        if not states or states[-1][1]!=state:
            states.append((when,state))
    diffs=[(curr[1]-last[1])%6
           for last,curr in zip(states,states[1:])]
    skipped=sum(d not in (1,5) for d in diffs)
    mixed=min(diffs.count(1),diffs.count(5))
    valid_fraction=len(usable)/len(triplets) if triplets else 0.0
    max_gap=max((later-earlier for earlier,later in
                 zip(usable,usable[1:])),default=0)
    enough=valid_fraction>=minimum_valid_fraction
    fresh=len(usable)>1 and max_gap<=maximum_valid_gap_ns
    coherent=(len(diffs)>=minimum_one_way_transitions and
              skipped==0 and mixed==0 and enough and fresh)
    return {
        "rank_separation_codes":separation,
        "rank_samples_total":len(triplets),
        "valid_rank_samples":len(usable),
        "valid_rank_fraction":round(valid_fraction,6),
        "minimum_valid_rank_fraction":minimum_valid_fraction,
        "rank_samples_with_ambiguous_ties":rejected_ties,
        "max_valid_rank_sample_gap_ms":round(max_gap/1e6,6),
        "allowed_max_valid_rank_sample_gap_ms":
            maximum_valid_gap_ns/1e6,
        "rank_coverage_sufficient":enough,
        "rank_freshness_sufficient":fresh,
        "distinct_state_observations":len(states),
        "adjacent_one_way_steps":diffs.count(1),
        "adjacent_other_way_steps":diffs.count(5),
        "skipped_nonadjacent_steps":skipped,
        "mixed_order_direction_indicators":mixed,
        "diagnostic_consistent_rank_sequence_candidate_only":coherent,
        "Guest_windmill_direction_or_angle_qualified":False,
        "motor_rearm_permitted":False
    }

def validate_source(events, stages):
    if (len(stages)!=5 or [s[1] for s in stages]!=[0,200,0,200,0]
        or any(s[1]!=s[2] or s[3]!=1 for s in stages)
        or stages[2][0]<300):
        raise ValueError("Five immutable 0/200/0/200/0 DShot stages required")
    ds=[e for e in events if e["kind"]=="DSHOT"]
    commands=list(commands_for_scenario(stages))
    if len(ds)!=len(commands):
        raise ValueError("Guest ADC diagnostic lost independent DShot frames")
    for idx,(e,(stage,command)) in enumerate(zip(ds,commands)):
        if e["data"][:5]!=(idx,stage,command,0,0):
            raise ValueError("DShot source frame or stage was modified")
        if idx>=2 and abs(e["vns"]-ds[idx-1]["vns"]-1_000_000)>100:
            raise ValueError("DShot source 1kHz clock was modified")
    start=stages[0][0]+stages[1][0]
    restart=start+stages[2][0]
    return ds[start]["vns"],ds[restart]["vns"]


def correlate_guest_phase_epochs(events):
    """No rotor-model data; EOC must precede real ADCRESULT read.

    Triplets are matched by per-ADC EOC sequence. This is valid for
    all-ADC PendSV schedule only if all three EOC/READ epochs agree and
    the three actual read timestamps remain close; ambiguity fails.
    """
    eoc={}
    reads={}
    highest_eoc=[0,0,0]
    highest_read=[0,0,0]
    counts={"eoc":0,"read":0}
    for e in events:
        kind=e["kind"]
        if kind not in ("ADC_PHASE_EOC","ADC_PHASE_READ"):
            continue
        a=e["data"]
        if len(a)<6:
            raise ValueError("Truncated native ADC phase-source record")
        instance,code,channel,soc,epoch,gate=a[:6]
        if (type(instance) is not int or instance not in range(3) or
            type(code) is not int or not 0<=code<=4095 or
            type(epoch) is not int or epoch<=0 or
            type(gate) is not int or gate not in (0,1) or
            (instance,soc,channel)!=PHASE_SOC[instance]):
            raise ValueError("Unsupported/forged Guest ADC SOC/channel/code")
        key=(instance,epoch)
        if kind=="ADC_PHASE_EOC":
            if epoch!=highest_eoc[instance]+1 or key in eoc:
                raise ValueError("Missing, duplicate or reordered ADC EOC epoch")
            highest_eoc[instance]=epoch
            eoc[key]=e
            counts["eoc"]+=1
        else:
            if epoch!=highest_read[instance]+1 or key in reads:
                raise ValueError("Missing, duplicate or reordered Guest ADCRESULT epoch")
            highest_read[instance]=epoch
            if key not in eoc or e["vns"]<eoc[key]["vns"] or (
                e["vns"]-eoc[key]["vns"]>MAX_EOC_READ_NS):
                raise ValueError("Guest ADCRESULT read without matching fresh EOC")
            if code!=eoc[key]["data"][1]:
                raise ValueError("Guest ADCRESULT does not match native EOC")
            reads[key]=e
            counts["read"]+=1
    if not reads or not eoc or any(n==0 for n in highest_read):
        raise ValueError("Original Guest never read all three BEMF phase SOCs")
    if highest_read!=highest_eoc:
        raise ValueError("Unconsumed ADC phase EOC or dropped Guest ADCRESULT read")
    joined=[]
    for epoch in range(1,highest_read[0]+1):
        try:
            phases=[reads[(i,epoch)] for i in range(3)]
        except KeyError:
            raise ValueError("Missing coherent three-phase ADC Guest read epoch")
        times=[r["vns"] for r in phases]
        if max(times)-min(times)>MAX_THREE_PHASE_SKEW_NS:
            raise ValueError("ADC0/1/2 Guest reads cannot form fresh triplet")
        # *Guest-visible* voltage codes only; no source theta or RPM.
        joined.append({
            "vns":max(times),
            "epoch":epoch,
            "codes":[r["data"][1] for r in phases],
            "gates":[r["data"][5] for r in phases]
        })
    if not (highest_read[0]==highest_read[1]==highest_read[2]):
        raise ValueError("Guest phase ADC read epoch count mismatch")
    return joined,counts


def contrast_in_window(triplets,start,stop,profile=None):
    data=[r for r in triplets if start<=r["vns"]<stop]
    if len(data)<MIN_WINDOW_EPOCHS:
        return {
            "samples":len(data),
            "classification":"INSUFFICIENT_COHERENT_GUEST_ADC_SAMPLES",
            "max_phase_code_contrast":None,
            "diagnostic_code_floor":DIAGNOSTIC_CODE_CONTRAST_FLOOR,
            "direction_qualified":False,"rotor_phase_qualified":False
        }
    contrasts=[max(r["codes"])-min(r["codes"]) for r in data]
    profile=profile if profile is not None else load_rank_profile()
    rank=rank_motion_diagnostic(
        data,
        separation=profile["minimum_adjacent_phase_code_separation"],
        minimum_valid_fraction=profile["minimum_valid_rank_fraction"],
        maximum_valid_gap_ns=profile["maximum_valid_rank_sample_gap_ms"]*
                            1_000_000,
        minimum_one_way_transitions=profile["minimum_one_way_rank_transitions"])
    return {
        "samples":len(data),
        "max_phase_code_contrast":max(contrasts),
        "min_phase_code_contrast":min(contrasts),
        "diagnostic_code_floor":DIAGNOSTIC_CODE_CONTRAST_FLOOR,
        "classification":("INSUFFICIENT_QUANTIZED_GUEST_ADC_CONTRAST"
                          if max(contrasts)<DIAGNOSTIC_CODE_CONTRAST_FLOOR
                          else "GUEST_ADC_PHASE_CONTRAST_PRESENT_DIRECTION_UNPROVEN"),
        "direction_qualified":False,"rotor_phase_qualified":False,
        "rank_motion_diagnostic":rank
    }


def evaluate(events,stages,profile=None):
    coast_start,restart=validate_source(events,stages)
    triplets,counts=correlate_guest_phase_epochs(events)
    # The first 100ms can have substantial BEMF. The last 100ms is the
    # actual pre-restart decision window, not arbitrary later snapshots.
    early=contrast_in_window(triplets,coast_start,coast_start+EARLY_NS,profile)
    late=contrast_in_window(triplets,restart-LAST_NS,restart,profile)
    neutral=[r for r in triplets if coast_start+200_000_000<=r["vns"]<restart]
    late_motion=[e for e in events if
        coast_start+200_000_000<=e["vns"]<restart and
        e["kind"] in ("PWM_PAIR","CAP1_ACK","TIMG12_ACK")]
    if late_motion:
        raise ValueError("Coast Guest motor is still commutating after settle")
    return {
        "schema":"e62.sim.guest-phase-adc-coast-observability.v1",
        "source":"REAL_GUEST_ADCRESULT_READ_AFTER_NATIVE_QEMU_EOC",
        "frame_source_validated":True,
        "per_channel_counts":counts,
        "coherent_full_triplets":len(triplets),
        "coast_ms":stages[2][0],
        "early_coast_100ms":early,
        "pre_restart_100ms":late,
        "postsettle_guest_adc_triplets":len(neutral),
        "postsettle_guest_motor_event_count":len(late_motion),
        "diagnostic_floor_not_a_calibrated_product_threshold":True,
        "guest_adc_read_source_is_not_qemu_model_theta_or_omega":True,
        "passive_rotor_direction_qualified":False,
        "passive_rotor_phase_qualified":False,
        "motor_rearm_permitted":False,
        "original_P1_reacquisition_qualified":False,
        "hardware_qualified":False,
        "source_epoch_integrity_pass":True,
        "safe_observer_refusal_gate_pass":True
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--scenario",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--rank-profile",type=Path,default=RANK_PROFILE_PATH)
    args=p.parse_args()
    try:
        stages,_=load_native_scenario(args.scenario)
        result=evaluate(read_events(args.events),stages,
                        load_rank_profile(args.rank_profile))
    except (ValueError,TypeError,KeyError,IndexError,OSError) as e:
        result={
            "schema":"e62.sim.guest-phase-adc-coast-observability.v1",
            "source_epoch_integrity_pass":False,
            "safe_observer_refusal_gate_pass":False,
            "passive_rotor_direction_qualified":False,
            "motor_rearm_permitted":False,
            "failures":[type(e).__name__+": "+str(e)]
        }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("E62_GUEST_ADC_COHERENT_COAST "+json.dumps(result,sort_keys=True))
    return 0 if result.get("source_epoch_integrity_pass") else 1

if __name__=="__main__":
    raise SystemExit(main())
