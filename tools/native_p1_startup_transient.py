#!/usr/bin/env python3
"""Read-only original QEMU P1 startup source transient diagnosis; NEVER a PASS.

Compare first 50ms after first positive, source-clocked PA26 DShot
against original-Guest PWM pair, CAP1/TIMG12 feedback, native 1ms
rotor/current/torque. Does not inject motor drive or weaken strict gates.
"""
import argparse
import json
import re
from pathlib import Path

EVENT=re.compile(
    r"E62_P0_EVENT seq=(\d+) vns=(\d+) kind=(\w+) "
    r"a=(-?\d+) b=(-?\d+) c=(-?\d+) d=(-?\d+) e=(-?\d+) f=(-?\d+)"
)

def parse(path):
    events=[]
    last_seq=0;last_ns=-1
    with Path(path).open(errors="replace") as stream:
        for line in stream:
            if "E62_P0_EVENT " not in line:
                continue
            m=EVENT.search(line)
            if m is None:
                raise ValueError("Malformed source event: "+line[:160])
            seq,ns=map(int,m.group(1,2))
            if seq!=last_seq+1 or ns<last_ns:
                raise ValueError("Non-monotone original QEMU source events")
            last_seq,last_ns=seq,ns
            events.append({"ns":ns,"kind":m[3],
                           "d":list(map(int,m.groups()[3:]))})
    if not events:
        raise ValueError("No original native source events")
    return events

def measure(name,events):
    dshot=[e for e in events if e["kind"]=="DSHOT"]
    onset=next((e for e in dshot if e["d"][2]>0),None)
    if onset is None:
        raise ValueError("Missing positive physical DShot command")
    start=onset["ns"]
    segment=[e for e in events if start<=e["ns"]<start+50000000]
    rotor=[e for e in segment if e["kind"]=="ROTOR"]
    if len(rotor)<10:
        raise ValueError("Missing 10 native rotor/current 1ms samples")
    def first(kind,after=start):
        return next((e for e in events if e["kind"]==kind
                     and e["ns"]>=after),None)
    def rel(event):
        return round((event["ns"]-start)/1e6,6) if event else None
    pwm=first("PWM_PAIR")
    second=first("PWM_PAIR",pwm["ns"]+1) if pwm else None
    cap=first("CAP1")
    timg=first("TIMG12")
    reverse=next((e for e in rotor if e["d"][0]<=-50000),None)
    forward=next((e for e in rotor if e["d"][0]>=50000),None)
    negative_torque=next((e for e in rotor if e["d"][5]<-100000),None)
    return {
        "case":name,
        "status":"SOURCE_TRANSIENT_DIAGNOSTIC_NOT_QUALIFICATION",
        "qualified":False,
        "scope":"FIRST_50MS_AFTER_FIRST_POSITIVE_DSHOT_SIM_ONLY",
        "first_positive_dshot_value":onset["d"][2],
        "first_positive_frame":onset["d"][0],
        "first_positive_source_virtual_ns":start,
        "first_pwm_sector_ms":rel(pwm),
        "second_pwm_sector_ms":rel(second),
        "first_cap1_ms":rel(cap),
        "first_guest_cap1_ack_ms":rel(first("CAP1_ACK")),
        "first_timg12_ms":rel(timg),
        "first_guest_timg12_ack_ms":rel(first("TIMG12_ACK")),
        "first_forward_50rpm_ms":rel(forward),
        "first_reverse_50rpm_ms":rel(reverse),
        "first_negative_torque_0p1nm_ms":rel(negative_torque),
        "reverse_before_first_timg12":bool(reverse and timg and
                                           reverse["ns"]<timg["ns"]),
        "reverse_before_second_pwm_sector":bool(reverse and second and
                                                 reverse["ns"]<second["ns"]),
        "max_abs_phase_current_a":max(abs(x) for e in rotor
                                      for x in e["d"][2:5])/1000,
        "peak_positive_torque_nm":max(e["d"][5] for e in rotor)/1e6,
        "peak_negative_torque_nm":min(e["d"][5] for e in rotor)/1e6,
        "min_rpm":min(e["d"][0] for e in rotor)/1000,
        "max_rpm":max(e["d"][0] for e in rotor)/1000,
        "first_ten_samples":[{
            "ms":rel(e),"rpm":e["d"][0]/1000,
            "unwrapped_theta_rad":e["d"][1]/1000,
            "phase_currents_a":[i/1000 for i in e["d"][2:5]],
            "torque_nm":e["d"][5]/1e6,
        } for e in rotor[:10]],
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case",required=True,action="append",
                    help="NAME=PATH_TO_NATIVE_P0_EVENTS; repeat for A/B")
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    records=[]
    for item in args.case:
        if "=" not in item:
            ap.error("--case must be NAME=PATH")
        name,path=item.split("=",1)
        if not name or not path:
            ap.error("--case must be NAME=PATH")
        records.append(measure(name,parse(path)))
    result={"status":"DIAGNOSTIC_ONLY_NOT_P1_PASS",
            "qualified":False,"cases":records}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    for record in records:
        print("E62_P1_STARTUP_TRANSIENT "+json.dumps({
            "case":record["case"],"source_dshot":record["first_positive_dshot_value"],
            "peak_current_a":record["max_abs_phase_current_a"],
            "min_torque_nm":record["peak_negative_torque_nm"],
            "first_reverse_ms":record["first_reverse_50rpm_ms"],
            "first_timg12_ms":record["first_timg12_ms"],
            "reverse_before_first_timg12":record["reverse_before_first_timg12"],
        },sort_keys=True))

if __name__=="__main__":
    main()
