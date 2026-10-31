#!/usr/bin/env python3
"""SIM_ONLY source A/B observer, no change to Original P1 qualification."""
import argparse
import json
import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p0_strict import parse_events

ELF_SHA="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"

def _crossings(rows, index, target=None):
    """Linear interpolation between 1ms native QEMU rotor samples; estimate."""
    hits=[]
    for old,new in zip(rows,rows[1:]):
        y0,y1=old["data"][index],new["data"][index]
        boundaries=[target] if target is not None else []
        if target is None and index==1: # unwrapped rotor electrical milli-radians
            low=min(y0,y1); high=max(y0,y1)
            boundaries=[int(k*math.pi*1000) for k in
                        range(math.floor(low/(math.pi*1000))-1,
                              math.ceil(high/(math.pi*1000))+2)]
        for k in boundaries:
            if y1!=y0 and min(y0,y1) <= k <= max(y0,y1):
                frac=(k-y0)/(y1-y0)
                hits.append(int(old["vns"]+(new["vns"]-old["vns"])*frac))
    return sorted(set(hits))

def audit(events,evidence):
    assert evidence["original_elf_sha256"]==ELF_SHA,"Original firmware changed"
    assert evidence["host_guest_register_writes"] is False
    assert evidence["used_guest_wfi_or_gdb"] is False
    assert evidence["synthetic_timed_bemf_enabled"] is False
    assert evidence["pwm_source_before"]["effective_mcpwm_root_clock_hz"]==200000000
    assert evidence["motor_before"]["sim_bemf_waveform"]==evidence["requested_sim_bemf_waveform"]
    dshot=[e for e in events if e["kind"]=="DSHOT"]
    assert len(dshot)==5100, "Source DShot must remain all 5100 exact frames"
    d0=next(e["vns"] for e in dshot if e["data"][1]==1 and e["data"][2]==448)
    pairs=[e for e in events if e["kind"]=="PWM_PAIR" and e["vns"]>=d0]
    assert pairs and pairs[0]["data"][:2]==(8,24),"First original power-pair changed"
    nextpair=next((e for e in pairs[1:] if e["data"][0]!=pairs[0]["data"][0]),None)
    assert nextpair,"No physical second power pair"
    sector=[e for e in events if pairs[0]["vns"]<=e["vns"]<nextpair["vns"]]
    rotors=[e for e in sector if e["kind"]=="ROTOR"]
    caps=[e for e in sector if e["kind"]=="CAP1"]
    t12=[e for e in sector if e["kind"]=="T12_LOAD"]
    first_after=next((e for e in t12 if caps and e["vns"]>=caps[0]["vns"]),None)
    torque_neg=next((r for r in rotors if r["data"][5]<-100000),None)
    rotor_negative=next((r for r in rotors if r["data"][0]<-50000),None)
    electrical_zeros=_crossings(rotors,1)
    speed_zeros=_crossings(rotors,0,0)
    def ms(ns):return round((ns-d0)*1e-6,4) if ns is not None else None
    def nearest(e, candidates):
        return (round(min((abs(e["vns"]-v),v) for v in candidates)[0]*1e-6,4)
                if e is not None and candidates else None)
    return {
        "scope":"SOURCE_QEMU_HYPOTHETICAL_PLANT_NOT_REAL_EC87",
        "waveform":evidence["requested_sim_bemf_waveform"],
        "vbus_mv":evidence["motor_before"]["effective_sim_motor_model"]["bus_millivolts"],
        "original_elf_sha256":ELF_SHA,
        "original_p1_unchanged":True,
        "dshot_frames":len(dshot),
        "mcpwm_root_hz":200000000,
        "first_pair":pairs[0]["data"][0],
        "first_pair_mask":pairs[0]["data"][1],
        "first_pair_start_ms":ms(pairs[0]["vns"]),
        "next_pair_ms":ms(nextpair["vns"]),
        "first_pair_duration_ms":round((nextpair["vns"]-pairs[0]["vns"])*1e-6,4),
        "first_cap1_ms":ms(caps[0]["vns"]) if caps else None,
        "second_cap1_ms":ms(caps[1]["vns"]) if len(caps)>1 else None,
        "first_post_cap1_t12_ms":ms(first_after["vns"]) if first_after else None,
        "first_negative_torque_ms":ms(torque_neg["vns"]) if torque_neg else None,
        "first_negative_rpm_ms":ms(rotor_negative["vns"]) if rotor_negative else None,
        "max_abs_phase_current_a":round(max((max(abs(v) for v in r["data"][2:5])
                                            for r in rotors),default=0)/1000,3),
        "max_positive_rpm":round(max((r["data"][0] for r in rotors),default=0)/1000,3),
        "min_rpm":round(min((r["data"][0] for r in rotors),default=0)/1000,3),
        "electrical_angle_zero_ms_estimates":[ms(t) for t in electrical_zeros],
        "rotor_speed_zero_ms_estimates":[ms(t) for t in speed_zeros],
        "first_cap_distance_to_angle_zero_ms_approx":nearest(caps[0] if caps else None,electrical_zeros),
        "second_cap_distance_to_angle_zero_ms_approx":nearest(caps[1] if len(caps)>1 else None,electrical_zeros),
        "second_cap_distance_to_speed_zero_ms_approx":nearest(caps[1] if len(caps)>1 else None,speed_zeros),
        "angle_zero_sampling_limit_ms":1.0,
        "inference_limitation":"Interpolated QEMU rotor samples, not external physical encoder; phase BEMF can cross zero when omega crosses zero.",
        "real_ec87_waveform_measured":False,
    }

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--events",type=Path,required=True)
    a.add_argument("--evidence",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    args=a.parse_args()
    events=parse_events(args.events.read_text().splitlines())
    report=audit(events,json.loads(args.evidence.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:v for k,v in report.items() if
       k in ("waveform","vbus_mv","first_cap1_ms","second_cap1_ms",
              "first_pair_duration_ms","first_negative_torque_ms",
              "first_negative_rpm_ms","max_abs_phase_current_a",
              "min_rpm","second_cap_distance_to_speed_zero_ms_approx")},indent=2))

if __name__=="__main__":main()
