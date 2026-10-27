#!/usr/bin/env python3
"""Original-Guest *no-WFI* P0 source event gate: provenance, rotor and energy.

Every event must originate at a QEMU virtual-hardware callback, never
from a host-derived duty estimate or synthetic BEMF. Temporal ordering
plus original Guest IRQ telemetry is evidence, not causal proof by
counts alone. Strict gates are NEVER silently waived.
"""
import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

EVENT = re.compile(
    r"E62_P0_EVENT seq=(\d+) vns=(-?\d+) kind=([A-Z_0-9]+) "
    r"a=(-?\d+) b=(-?\d+) c=(-?\d+) d=(-?\d+) "
    r"e=(-?\d+) f=(-?\d+)"
)
KINDS={"CMP_FILTER","CAP1","TIMG12","PWM_PAIR","ROTOR",
       "ENERGY","INVARIANT","SWITCH","SWITCH_CURRENT",
       "CAP1_ACK","TIMG12_ACK","DSHOT","BEMF_FRONTEND","OC_FRONTEND"}
STABILITY_MIN_SECTORS=12
STABILITY_MIN_TIME_NS=90_000_000
SIGNIFICANT_SPEED_RPM=50.0
MAX_EVENT_RECORDS=200_000


class TraceError(ValueError):
    pass


def parse_events(lines):
    events=[]
    prev_seq=prev_time=None
    for text in lines:
        if "E62_P0_EVENT " not in text:
            continue
        m=EVENT.search(text)
        if not m:
            raise TraceError("Malformed source event")
        seq=int(m[1]);vns=int(m[2]);kind=m[3]
        values=tuple(int(m[j]) for j in range(4,10))
        if kind not in KINDS or seq < 1 or vns < 0:
            raise TraceError("Unknown kind or invalid clock/seq")
        if prev_seq is not None and (seq!=prev_seq+1 or vns<prev_time):
            raise TraceError("Missing/reordered event or time reversal")
        events.append({"seq":seq,"vns":vns,"kind":kind,"data":values})
        prev_seq,prev_time=seq,vns
        if len(events)>MAX_EVENT_RECORDS:
            raise TraceError("Event budget exceeded; incomplete source")
    if not events or events[0]["seq"]!=1:
        raise TraceError("Trace absent or first source event missing")
    return events


def audit(events, evidence, physics=None):
    counts=Counter(e["kind"] for e in events)
    flags=[]
    guest=evidence.get("original_guest_after") or {}
    auto=evidence.get("autonomous_dshot") or {}
    motor=evidence.get("native_motor") or {}
    if (evidence.get("original_elf_sha256") !=
        "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"):
        flags.append("ORIGINAL_ELF_NOT_PINNED")
    if evidence.get("host_guest_register_writes") is not False or (
        evidence.get("used_guest_wfi_or_gdb") is not False):
        flags.append("NOT_AUTONOMOUS_OR_GUEST_WRITES")
    if evidence.get("synthetic_timed_bemf_enabled") is not False or (
        evidence.get("legacy_synthetic_bemf_callbacks") != 0):
        flags.append("ARTIFICIAL_BEMF_PRESENT")
    if auto.get("sent") != evidence.get("configured_dshot_frames") or (
        auto.get("sent",0)<300):
        flags.append("CONTINUOUS_DSHOT_INCOMPLETE")
    if physics is None or physics.get("qualified") is not True:
        flags.append("INDEPENDENT_FROZEN_SWITCH_PHYSICS_NOT_QUALIFIED")
    if guest.get("valid_frame_feeds",0)<1:
        flags.append("NO_ORIGINAL_DSHOT_CRC")
    if guest.get("serviced",0)<STABILITY_MIN_SECTORS:
        flags.append("INSUFFICIENT_GUEST_CAPTURE_ISR_SERVICE")
    if motor.get("model_fault",1)!=0 or (motor.get("status_flags",0)&4):
        flags.append("NATIVE_MOTOR_FAILED")
    if motor.get("ost3_latch_activations",1)!=0:
        flags.append("PHYSICAL_OC_TRIP_LATCHED")
    if (evidence.get("receiver_after") or {}).get("native_pwm_trip_latch",1)!=0:
        flags.append("PWM_TRIP_ACTIVE_AT_END")
    for kind in ("CMP_FILTER","CAP1","TIMG12","PWM_PAIR",
                 "ROTOR","ENERGY","INVARIANT","SWITCH"):
        if counts[kind]==0:
            flags.append("NO_SOURCE_"+kind)

    # Ordered source-callback evidence: CMPSS filtered event, enabled
    # CAP1, native TIMG12 ZERO and subsequently changed original six-pad
    # power pair. No fabricated Guest ISR timing is inserted.
    last_comp=last_cap=last_cap_ack=last_t12=last_t12_ack=None
    chains=[]
    seen_pairs=set()
    last_pair=None
    for event in events:
        t=event["vns"]
        typ=event["kind"]
        if typ=="CMP_FILTER":
            last_comp=event
        elif typ=="CAP1":
            if (last_comp and t-last_comp["vns"]<=3_000_000 and
                event["data"][1]==last_comp["data"][0]):
                last_cap=(last_comp,event)
        elif typ=="CAP1_ACK":
            if (last_cap and t-last_cap[1]["vns"]<=3_000_000):
                last_cap_ack=(*last_cap,event)
        elif typ=="TIMG12":
            if (last_cap_ack and t-last_cap_ack[2]["vns"]<=3_000_000):
                last_t12=(*last_cap_ack,event)
        elif typ=="TIMG12_ACK":
            if last_t12 and t-last_t12[3]["vns"]<=3_000_000:
                last_t12_ack=(*last_t12,event)
        elif typ=="PWM_PAIR":
            pair=event["data"][0]
            if pair==last_pair:
                continue
            last_pair=pair
            if (last_t12_ack and t-last_t12_ack[4]["vns"]<=3_000_000 and
                event["data"][2]&15==15):
                chains.append({
                    "cmp_ns":last_t12_ack[0]["vns"],
                    "cap1_ns":last_t12_ack[1]["vns"],
                    "guest_cap1_ack_ns":last_t12_ack[2]["vns"],
                    "timg12_ns":last_t12_ack[3]["vns"],
                    "guest_timg12_ack_ns":last_t12_ack[4]["vns"],
                    "pwm_pair_ns":t,
                    "pair":pair
                })
                seen_pairs.add(pair)
                last_t12_ack=None
    if len(chains)<STABILITY_MIN_SECTORS:
        flags.append("NO_12_SOURCE_ORDERED_CAUSAL_CHAINS")
    if len(chains)>=STABILITY_MIN_SECTORS and (
        chains[-1]["pwm_pair_ns"]-chains[0]["pwm_pair_ns"] <
        STABILITY_MIN_TIME_NS):
        flags.append("LESS_THAN_90MS_SOURCE_SECTOR_SPAN")
    if len(seen_pairs)<3:
        flags.append("UNQUALIFIED_SECTOR_DIVERSITY")

    rotor=[e for e in events if e["kind"]=="ROTOR"]
    peak_rpm=max((abs(e["data"][0])/1000 for e in rotor),default=0)
    angles_monotonic=True
    angular_violations=0
    significant_signs=set()
    for e in rotor:
        rpm=e["data"][0]/1000
        if abs(rpm)>=SIGNIFICANT_SPEED_RPM:
            significant_signs.add(1 if rpm>0 else -1)
    for left,right in zip(rotor,rotor[1:]):
        dt=(right["vns"]-left["vns"])*1e-9
        if dt<=0:
            angular_violations+=1;continue
        measured=(right["data"][1]-left["data"][1])/1000
        estimated=(left["data"][0]+right["data"][0])/2000*(
            2*math.pi/60*21*dt)
        if abs(measured-estimated)>0.025+0.1*abs(estimated):
            angular_violations+=1
    if peak_rpm<SIGNIFICANT_SPEED_RPM:
        flags.append("ROTOR_NEVER_REACHES_SIGNIFICANT_SPEED")
    if len(significant_signs)>1:
        flags.append("SIGNIFICANT_ROTOR_DIRECTION_REVERSAL")
    if angular_violations:
        flags.append("ROTOR_ANGLE_SPEED_KINEMATICS_INCONSISTENT")

    energies=[e for e in events if e["kind"]=="ENERGY"]
    invs=[e for e in events if e["kind"]=="INVARIANT"]
    max_ledger_residual_nj=0
    for e in energies:
        bus,diode,copper,bemf,magnetic,euler=e["data"]
        max_ledger_residual_nj=max(
            max_ledger_residual_nj,
            abs(bus-diode-copper-bemf-magnetic-euler))
        if diode<0 or copper<0 or euler<0:
            flags.append("NEGATIVE_DISSIPATION_OR_NUMERICAL_LOSS")
    # Each ledger field has +/-0.5 nJ quantization; 6 terms permit
    # at most 3 nJ disagreement from source integer serialization.
    if max_ledger_residual_nj>6:
        flags.append("NATIVE_ELECTRICAL_ENERGY_IDENTITY_FAILED")
    if any(v["data"][4]>10 for v in invs):
        flags.append("STAR_KCL_VIOLATION_GT_10_MICROAMP")
    if any(v["data"][3]>10000 for v in invs):
        flags.append("STEP_ENERGY_RESIDUAL_GT_10_NJ")
    if invs and invs[-1]["data"][1]==0:
        flags.append("FREEWHEEL_DIODE_NOT_EXERCISED")

    # Observe full encoded waveform; independently re-validate its
    # time/edge sequencing before an optional numerical replay.
    switches=[e for e in events if e["kind"]=="SWITCH"]
    switch_currents=[e for e in events if e["kind"]=="SWITCH_CURRENT"]
    if (len(switches)!=len(switch_currents) or any(
        a["vns"]!=b["vns"] or
        b["data"][:3]!=b["data"][3:]
        for a,b in zip(switches,switch_currents))):
        flags.append("NATIVE_INSTANTANEOUS_SWITCH_CURRENT_DISCONTINUITY")
    if len(switches)<2:
        flags.append("INSUFFICIENT_NATIVE_SWITCH_HISTORY")
    if switches and (switches[-1]["vns"]-switches[0]["vns"])<90_000_000:
        flags.append("NATIVE_SWITCH_HISTORY_LT_90MS")
    if any((x["data"][0]&0x15 and x["data"][0]&0x2a and
            any((x["data"][0]&(3<<(2*k)))==3<<(2*k)
                for k in range(3))) for x in switches):
        flags.append("UNSAFE_SAME_LEG_OVERLAP")
    flags=list(dict.fromkeys(flags))
    strict=not flags
    return {
        "status":"PASS_NATIVE_P0_STRICT" if strict else "FAIL_NATIVE_P0_STRICT",
        "qualified":strict,
        "unwaived_failure_reasons":flags,
        "source_events":len(events),
        "source_kinds":dict(counts),
        "physical_dshot_frames":auto.get("sent"),
        "original_guest_crc_feeds":guest.get("valid_frame_feeds"),
        "original_guest_cap1_isr_serviced":guest.get("serviced"),
        "source_ordered_chains":len(chains),
        "source_sector_unique_pairs":sorted(seen_pairs),
        "source_sector_span_ms":round((chains[-1]["pwm_pair_ns"]-chains[0]["pwm_pair_ns"])/1e6,3) if chains else 0,
        "chain_samples":chains[:20],
        "rotor_samples":len(rotor),
        "peak_abs_motor_rpm":peak_rpm,
        "significant_rotor_direction_signs":sorted(significant_signs),
        "angle_speed_inconsistencies":angular_violations,
        "physics_energy_max_serialized_residual_nj":max_ledger_residual_nj,
        "physics_last_source_invariants":invs[-1]["data"] if invs else None,
        "full_120ms_switch_record_count":len(switches),
        "physical_motor_calibrated":False,
        "inference_warning":"Ordered hardware callbacks are not a formal proof that the Guest ISR caused the next switching action; do not substitute counts for trace",
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--evidence",type=Path,required=True)
    p.add_argument("--physics",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    try:
        evidence=json.loads(a.evidence.read_text())
        physics=json.loads(a.physics.read_text())
        with a.events.open(errors="replace") as handle:
            result=audit(parse_events(handle),evidence,physics)
    except (TraceError,ValueError,OSError,KeyError,TypeError) as exc:
        result={"status":"FAIL_NATIVE_P0_STRICT","qualified":False,
                "unwaived_failure_reasons":["MALFORMED_OR_MISSING_SOURCE_TRACE"],
                "error":str(exc)}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("E62_NATIVE_P0_STRICT "+json.dumps(result,sort_keys=True))
    if not result["qualified"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
