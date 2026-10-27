#!/usr/bin/env python3
"""Original Guest P1 *source-only* startup electrical geometry audit.

Inspect first real six-pad PWM_PAIR / SWITCH, signed three-phase currents,
unwrapped rotor electrical angle, independently reconstructed source torque,
BEMF and first CMPSS->CAP1->TIMG12 feedback. No guest writes or pass waivers.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.native_p0_strict import parse_events
from tools.native_closed_loop_audit import ORIGINAL_REL17_ROUTE

KT=0.0649
OFFSETS=(0.0,-2*math.pi/3,2*math.pi/3)
FIVE_EVENTS=("CMP_FILTER","CAP1","CAP1_ACK","TIMG12","TIMG12_ACK")
CASES=("smoke","gentle","direct20","steps")
ROTOR_MINIMUM_SAMPLES=3
PINNED_ELF="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"

def torque_from_trace(data):
    """Rounding-aware independent check of model's continuous-current torque.
    Source: current in mA, unwrapped angle in mrad, torque in uNm."""
    theta_post=data[1]/1000
    # Source motor_current_step computes torque against pre-integration
    # theta, then advances theta using mean(old_omega,omega). The ROTOR
    # event reports the post-integration theta and last torque. Retrodict
    # the 1us prior electrical phase from observed post-step omega. This
    # is read-only, and does not alter the QEMU integrator or observations.
    mechanical_omega=data[0]/1000*(2*math.pi/60)
    theta_pre=theta_post-21.0*mechanical_omega*1e-6
    current=[x/1000 for x in data[2:5]]
    calculated=KT*sum(i*math.sin(theta_pre+o)
                      for i,o in zip(current,OFFSETS))
    # Input quantization (3 x 0.5mA, angle 0.5mrad, RPM 0.5mRPM),
    # QEMU 1us pre-step approximation, last torque 0.5uNm.
    # Physical angular acceleration contribution at the simulated
    # 1us period is second order; account explicitly for bounded
    # observed torque/J and 21 pole-pairs (J=1.3e-4 kg.m^2).
    max_current=sum(abs(i) for i in current)
    accel_error=21.0*abs(data[5]/1e6)/0.00013*0.5e-12
    allowance=KT*(0.0015+(0.0005+accel_error)*max_current)+0.000002
    return calculated,data[5]/1e6,allowance

def pair_geometry(event):
    d=event["data"]
    mask=d[1]&63
    hi=[p for p in range(3) if mask & (1<<(2*p))]
    lo=[p for p in range(3) if mask & (1<<(2*p+1))]
    valid=len(hi)==1 and len(lo)==1 and hi[0]!=lo[0]
    if not valid:
        return {"vns":event["vns"],"mask":mask,
                "valid_power_pair":False,"pair_code":d[0]}
    theta=d[3]/1000
    factor=(math.sin(theta+OFFSETS[hi[0]])-
            math.sin(theta+OFFSETS[lo[0]]))
    return {
        "vns":event["vns"],"seq":event["seq"],
        "mask":mask,"gate_word":d[2],"pwm_zero_events":d[4],
        "pair_code":d[0],"hi_phase":hi[0],"lo_phase":lo[0],
        "source_pair_code_consistent":d[0]==1+3*hi[0]+lo[0],
        "matches_a_pinned_original_sixstep_pair":
            (hi[0],lo[0]) in [x[1] for x in ORIGINAL_REL17_ROUTE[1:]],
        "theta_unwrapped_electrical_deg":math.degrees(theta),
        "positive_source_to_sink_current_torque_basis":factor,
        "ideal_source_to_sink_current_would_generate_forward_torque":factor>0,
        "valid_power_pair":True,
        "not_a_measured_current_direction":True,
    }

def source_signature(events):
    """Early source DShot, original six-pad sector and CAP1/TIMG12 timing."""
    dshot=[e for e in events if e["kind"]=="DSHOT" and e["data"][2]>0]
    if not dshot:
        raise ValueError("Missing positive source PA26 DShot")
    onset=dshot[0]["vns"]
    t12=next((e for e in events if e["kind"]=="TIMG12" and
              e["vns"]>=onset),None)
    before_t12=t12["vns"] if t12 else None
    rotor=[e for e in events if e["kind"]=="ROTOR" and
           onset<=e["vns"]<onset+50_000_000]
    if len(rotor)<ROTOR_MINIMUM_SAMPLES:
        raise ValueError("Missing 1ms source rotor samples")
    pwm=[e for e in events if e["kind"]=="PWM_PAIR" and
         onset<=e["vns"]<onset+50_000_000]
    switch=[e for e in events if e["kind"]=="SWITCH" and
            onset<=e["vns"]<onset+50_000_000]
    before=(lambda event: before_t12 is None or
            event["vns"]<before_t12)
    feedback={}
    for kind in FIVE_EVENTS:
        match=next((e for e in events if e["kind"]==kind and
                    e["vns"]>=onset),None)
        feedback[kind]=(round((match["vns"]-onset)/1e6,6)
                        if match else None)
    negative=next((e for e in rotor if e["data"][5]<-100000),None)
    reverse=next((e for e in rotor if e["data"][0]<=-50000),None)
    first_high=next((e for e in rotor if max(abs(x) for x in
                      e["data"][2:5])>=10000),None)
    mis=[]
    checked=0
    worst=0.0
    samples=[]
    for e in rotor:
        predicted,measured,allowance=torque_from_trace(e["data"])
        delta=abs(predicted-measured)
        worst=max(worst,delta)
        checked+=1
        if delta>allowance:
            mis.append({"virtual_ns":e["vns"],"predicted_nm":predicted,
                        "source_nm":measured,"allowance_nm":allowance})
        if e["vns"]<onset+20_000_000:
            samples.append({
                "relative_ms":round((e["vns"]-onset)/1e6,6),
                "rpm":e["data"][0]/1000,
                "theta_elec_deg_unwrapped":round(math.degrees(
                    e["data"][1]/1000),3),
                "iabc_a":[x/1000 for x in e["data"][2:5]],
                "source_torque_nm":measured,
                "independently_reconstructed_torque_nm":round(predicted,6),
                "before_first_timg12":before(e),
            })
    sector=[pair_geometry(e) for e in pwm]
    # The 120ms SWITCH log is complete only in this short initial
    # startup window. A switching event is the AQ/DB physical six-pad
    # output, whereas PWM_PAIR records one-high/one-low only at
    # pair transitions, NOT its carrier duty-cycle.
    masks={}
    for e in switch:
        key=f"0x{e['data'][0]:02x}"
        masks[key]=masks.get(key,0)+1
    firstpair=sector[0] if sector else None
    first_neg_geom=next((x for x in sector if x.get(
        "valid_power_pair") and
        x["positive_source_to_sink_current_torque_basis"]<0),None)
    pre_feedback_rotor=[e for e in rotor if before(e)]
    pre_feedback_pairs=[p for p in sector if before(p)]
    return {
        "status":"SOURCE_ONLY_DIAGNOSTIC_NOT_A_P1_VERDICT",
        "origin_dshot_virtual_ns":onset,
        "first_positive_dshot_value":dshot[0]["data"][2],
        "first_feedback_relative_ms":feedback,
        "first_negative_torque_relative_ms":(round(
            (negative["vns"]-onset)/1e6,6) if negative else None),
        "first_reverse_50rpm_relative_ms":(round(
            (reverse["vns"]-onset)/1e6,6) if reverse else None),
        "first_current_ge10a_relative_ms":(round(
            (first_high["vns"]-onset)/1e6,6) if first_high else None),
        "negative_torque_before_first_timg12":(
            before(negative) if negative else None),
        "negative_speed_before_first_timg12":(
            before(reverse) if reverse else None),
        "source_torque_reconstruction":{
            "checked_rotor_samples":checked,"mismatch_count":len(mis),
            "mismatch_examples":mis[:4],
            "max_abs_residual_nm":round(worst,9),
            "angle_alignment":"PRE_1US_STEP_ESTIMATED_FROM_POSTSTEP_RPM",
            "last_torque_precedes_reported_rotor_angle":True,
            "rounding_aware_tolerance_only_not_p1_waiver":True,
        },
        "pre_first_timg12":{
            "rotor_sample_count":len(pre_feedback_rotor),
            "first50ms_min_torque_nm":min(
                (e["data"][5]/1e6 for e in pre_feedback_rotor),
                default=None),
            "first50ms_max_abs_current_a":max(
                (abs(x)/1000 for e in pre_feedback_rotor
                 for x in e["data"][2:5]),default=None),
            "full_power_pairs":len(pre_feedback_pairs),
            "reverse_ge50rpm_samples":sum(
                e["data"][0]<=-50000 for e in pre_feedback_rotor),
            "first_pair":firstpair,
            "first_negative_geometric_pair":first_neg_geom,
            "all_pre_timg12_pair_geometries":pre_feedback_pairs[:80],
        },
        "first_50ms_power_pair_count":len(sector),
        "first_50ms_power_pair_invalid_count":sum(
            not x["valid_power_pair"] or
            not x.get("source_pair_code_consistent",False)
            for x in sector),
        "first_50ms_switch_count":len(switch),
        "first_50ms_sixpad_mask_histogram":masks,
        "first_20ms_rotor_current_torque":samples,
        "qualification":False,
        "physical_motor_calibrated":False,
        "do_not_attribute_cause_from_event_order_alone":True,
    }

def analyze_records(records):
    cases=[]
    issues=[]
    for name,trace,verdict in records:
        try:
            with Path(trace).open(errors="replace") as stream:
                events=parse_events(stream)
            source=json.loads(Path(verdict).read_text())
            if source.get("status") not in (
                  "PASS_P1_SIM_ONLY_OBSERVABILITY",
                  "FAIL_P1_SIM_ONLY_OBSERVABILITY"):
                raise ValueError("Missing valid source P1 verdict")
            result=source_signature(events)
            result["name"]=name
            result["p1_source_status"]=source["status"]
            result["p1_source_failures"]=source.get(
                "unwaived_observability_failures",[])
            result["p1_source_qualified"]=source.get("qualified")
            if result["source_torque_reconstruction"]["mismatch_count"]:
                issues.append(name+": TORQUE_RECONSTRUCTION_DISAGREEMENT")
            if result["first_50ms_power_pair_invalid_count"]:
                issues.append(name+": PHYSICAL_PAIR_MASK_MISMATCH")
        except (OSError,ValueError,KeyError,TypeError) as exc:
            result={"name":name,"status":"MISSING_OR_INVALID_SOURCE",
                    "error":str(exc)}
            issues.append(name+": "+str(exc))
        cases.append(result)
        pf=result.get("pre_first_timg12",{})
        print("E62_P1_EARLY_GEOMETRY "+json.dumps({
            "case":name,
            "p1":result.get("p1_source_status"),
            "first_dshot":result.get("first_positive_dshot_value"),
            "first_pair":pf.get("first_pair"),
            "first_negative_geometric_pair":pf.get(
                "first_negative_geometric_pair"),
            "first_negative_torque_ms":result.get(
                "first_negative_torque_relative_ms"),
            "first_reverse_50rpm_ms":result.get(
                "first_reverse_50rpm_relative_ms"),
            "first_timg12_ms":result.get(
                "first_feedback_relative_ms",{}).get("TIMG12"),
            "pre_timg12_min_torque_nm":pf.get("first50ms_min_torque_nm"),
            "pre_timg12_peak_current_a":pf.get("first50ms_max_abs_current_a"),
            "pre_timg12_power_pairs":pf.get("full_power_pairs"),
            "torque_reconstruction_mismatches":result.get(
                "source_torque_reconstruction",{}).get("mismatch_count"),
            "torque_reconstruction_max_residual_nm":result.get(
                "source_torque_reconstruction",{}).get("max_abs_residual_nm"),
            "torque_reconstruction_mismatch_examples":result.get(
                "source_torque_reconstruction",{}).get("mismatch_examples"),
        },sort_keys=True),flush=True)
    return {"status":"COMPLETE_SOURCE_ONLY_GEOMETRY" if not issues else
            "FAIL_CLOSED_SOURCE_GEOMETRY_INCOMPLETE",
            "diagnostic_only":True,"qualified":False,
            "issues":issues,"cases":cases}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-root",type=Path,
                    default=ROOT/"artifacts/e62-p1-scripted")
    ap.add_argument("--output",type=Path,
                    default=ROOT/"artifacts/e62-p1-scripted/e62-p1-early-geometry.json")
    args=ap.parse_args()
    records=[(name,
              args.input_root/f"e62-p1-script-{name}.p0.events.log",
              args.input_root/f"e62-p1-script-{name}.p1.json")
             for name in CASES]
    report=analyze_records(records)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,sort_keys=True,
                           indent=2)+"\n")
    sys.exit(0 if not report["issues"] else 1)

if __name__=="__main__":
    main()
