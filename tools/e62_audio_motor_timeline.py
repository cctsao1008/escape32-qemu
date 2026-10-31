#!/usr/bin/env python3
"""Read-only hardware-clock/audio-candidate versus rotor-drive timeline.

Only first-party QEMU virtual-clock events are admitted. Div32 and note-like
period writes are *hardware evidence* consistent with Rel17 music, NOT a
read of the firmware-private audio_owner variable. No model drive, no Guest
write, no new P1 acceptance or hardware qualification.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p0_strict import parse_events, TraceError

ORIGINAL_SHA="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
SIX_STEP_CANON=(8,2,3,6,4,7)
CANDIDATE_AUDIO_DIV=5  # QEMU 200MHz / 32 = 6.25MHz.

def _pair_from_mask(mask):
    high=[p for p in range(3) if mask & (1 << (2*p))]
    low=[p for p in range(3) if mask & (1 << (2*p+1))]
    if len(high)!=1 or len(low)!=1 or high[0]==low[0]:
        return None
    return 1+3*high[0]+low[0]

def analyze(events, evidence, scenario):
    if (evidence.get("original_elf_sha256")!=ORIGINAL_SHA or
        evidence.get("host_guest_register_writes") is not False or
        evidence.get("used_guest_wfi_or_gdb") is not False or
        evidence.get("experimental_candidate_not_original") is not False):
        raise ValueError("Pinned Original Guest or source-wiring evidence missing")
    if (scenario.get("schema")!="e62.native.dshot.v1" or
        scenario.get("guest_ready_gating") is not False or
        scenario.get("protocol")!="DSHOT600" or
        scenario.get("frame_period_ns")!=1000000):
        raise ValueError("Unexpected source DShot scenario")
    stages=scenario.get("stages",[])
    if (len(stages)!=5 or
        [s.get("permille") for s in stages]!=[0,200,0,200,0] or
        any(s.get("kind")!="hold" or
            type(s.get("duration_ms")) is not int or
            s["duration_ms"]<=0 for s in stages)):
        raise ValueError("Source DShot stages unrecognized")
    ds=[x for x in events if x["kind"]=="DSHOT"]
    count=sum(s["duration_ms"] for s in stages)
    if len(ds)!=count or any(e["data"][0]!=i for i,e in enumerate(ds)):
        raise ValueError("Missing/unordered actual source DShot frames")
    if (evidence.get("configured_dshot_frames")!=count or
        (evidence.get("autonomous_dshot") or {}).get("sent")!=count):
        raise ValueError("Actual source/evidence DShot count mismatch")
    borders=[0]
    for s in stages:
        borders.append(borders[-1]+s["duration_ms"])
    intervals=[(ds[borders[i]]["vns"],
                ds[borders[i+1]]["vns"] if i+1<len(stages)
                else ds[-1]["vns"]+1000000)
               for i in range(len(stages))]
    mode=[x for x in events if x["kind"]=="PWM_TBCTL"]
    note=[x for x in events if x["kind"]=="PWM_AUDIO_PERIOD"]
    audio=[x for x in mode if ((x["data"][1]>>2)&15)==CANDIDATE_AUDIO_DIV]
    drive=[x for x in mode if ((x["data"][1]>>2)&15)==1]
    all_candidates=audio+note
    positive=[intervals[1],intervals[3]]
    mid_audio=[x for x in all_candidates if
               any(a<=x["vns"]<b for a,b in positive)]
    # Raw hardware source events are not an assertion of firmware ownership.
    pair_events=[x for x in events if x["kind"]=="PWM_PAIR"]
    stage_info=[]
    for i,(a,b) in enumerate(intervals):
        pairs=[x for x in pair_events if a<=x["vns"]<b]
        rotor=[x for x in events if x["kind"]=="ROTOR" and
               a<=x["vns"]<b]
        speeds=[x["data"][0]/1000.0 for x in rotor]
        invalid=[x for x in pairs if
                 _pair_from_mask(x["data"][1])!=x["data"][0]]
        ordered=[x["data"][0] for x in pairs]
        nonadj=sum(1 for p,q in zip(ordered,ordered[1:])
                   if (p not in SIX_STEP_CANON or
                       q!=SIX_STEP_CANON[(SIX_STEP_CANON.index(p)+1)%6]))
        stage_info.append({
            "stage":i, "command_permille":stages[i]["permille"],
            "dshot_frames":stages[i]["duration_ms"],
            "rotor_samples":len(rotor),
            "min_rpm":min(speeds) if speeds else None,
            "max_rpm":max(speeds) if speeds else None,
            "significant_positive_samples":sum(v>=50 for v in speeds),
            "significant_negative_samples":sum(v<=-50 for v in speeds),
            "motor_power_pair_events":len(pairs),
            "pair_mask_encoding_errors":len(invalid),
            "not_canonical_six_step_neighbors":nonadj,
            "first_pairs":ordered[:12],
            "candidate_audio_clock_writes":sum(a<=x["vns"]<b for x in audio),
            "candidate_audio_note_period_writes":sum(a<=x["vns"]<b for x in note)
        })
    first_demand=positive[0][0]
    last_audio_before=[e["vns"] for e in all_candidates
                       if e["vns"]<first_demand]
    post_audio_div2=[e["vns"] for e in drive
                     if last_audio_before and
                     last_audio_before[-1]<=e["vns"]<first_demand]
    return {
        "schema":"e62.sim.audio-motor-source-timeline.v1",
        "classification":"SIM_ONLY_QEMU_MCPWM_REGISTER_SOURCE_DIAGNOSTIC",
        "source_trace_events":len(events),
        "original_elf_sha256":ORIGINAL_SHA,
        "guest_audio_owner_directly_observed":False,
        "clock_div32_is_music_candidate_not_proof":True,
        "audio_candidate_before_first_demand":bool(last_audio_before),
        "audio_period_events_before_first_demand":sum(
            e["vns"]<first_demand for e in note),
        "clock_div2_write_after_last_audio_before_first_demand":
            bool(post_audio_div2),
        "audio_candidate_in_positive_demands":len(mid_audio),
        "mode_writes":len(mode),"audio_clock_mode_writes":len(audio),
        "audio_period_writes":len(note),
        "first_demand_vns":positive[0][0],
        "second_demand_vns":positive[1][0],
        "stage_evidence":stage_info,
        "p1_qualified":False,"hardware_qualified":False,
        "interpretation":(
            "AUDIO_CLOCK_CANDIDATE_INSIDE_POSITIVE_DEMAND_INVESTIGATE"
            if mid_audio else
            "NO_NEW_AUDIO_CLOCK_CANDIDATE_IN_POSITIVE_DEMAND_NOT_EXCLUSION"
        ),
        "limitations":"QEMU TBCTL divider/period are hardware proxies, not firmware audio_owner; PWM-pair sequence does not validate physical wiring or motor torque polarity"
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events",type=Path,required=True)
    ap.add_argument("--evidence",type=Path,required=True)
    ap.add_argument("--scenario",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args()
    try:
        with a.events.open(errors="replace") as h:
            ev=parse_events(h)
        result=analyze(ev,json.loads(a.evidence.read_text()),
                       json.loads(a.scenario.read_text()))
    except (TraceError,ValueError,TypeError,KeyError,OSError) as exc:
        result={"schema":"e62.sim.audio-motor-source-timeline.v1",
                "classification":"SIM_ONLY_SOURCE_DIAGNOSTIC_FAIL_CLOSED",
                "source_valid":False,
                "error":str(exc),
                "p1_qualified":False,"hardware_qualified":False}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("E62_AUDIO_MOTOR_TIMELINE "+json.dumps(result,sort_keys=True))
    return 0 if result.get("source_valid",True) else 1

if __name__=="__main__":
    raise SystemExit(main())
