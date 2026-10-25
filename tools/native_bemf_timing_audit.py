#!/usr/bin/env python3
"""G17/G18 read-only BEMF/ECAP/TIMG12 forensic audit of original Guest WFI.

A WFI snapshot is a SAMPLE, not the comparator's analog transition time.
Threshold crossings are interval-bracketed estimates; do not infer an exact
zero crossing, physical analog timing, or physical motor qualification.
"""
import argparse
import bisect
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_closed_loop_audit import ORIGINAL_REL17_ROUTE

OFFSETS = (0., -2*math.pi/3, 2*math.pi/3)
TWO_PI = 2*math.pi
DAC_THRESHOLD = 2048
BIAS_V = 1.65
GAIN = .02
VREF = 3.3


def _shortest_angle(a, b):
    return (b-a+math.pi) % (2*math.pi)-math.pi


def _angle_at(samples, times, ns):
    """Piecewise WFI electrical-angle interpolation; explicitly estimated."""
    if ns < times[0] or ns > times[-1]:
        return None
    i = bisect.bisect_right(times, ns)
    if i == 0:
        return None
    if i == len(samples):
        return math.degrees(samples[-1]["electrical_rad"]) % 360
    left, right = samples[i-1], samples[i]
    weight = (ns-left["t_ns"])/(right["t_ns"]-left["t_ns"])
    angle = (left["electrical_rad"] +
             weight*_shortest_angle(left["electrical_rad"],
                                    right["electrical_rad"]))
    return math.degrees(angle) % 360


def _threshold_crossings(samples):
    """Infer a threshold crossing only from consecutive OBSERVED WFI codes."""
    result = []
    for a,b in zip(samples, samples[1:]):
        for phase in range(3):
            a_code, b_code = a["analog_adc_codes"][phase], b["analog_adc_codes"][phase]
            high_before = a_code > DAC_THRESHOLD
            high_after = b_code > DAC_THRESHOLD
            if high_before == high_after:
                continue
            # A transition is guaranteed somewhere inside the sample interval
            # *if* the underlying signal is continuous. Time is interpolated
            # only as a central estimate; do NOT use as an exact comparator edge.
            fraction = ((DAC_THRESHOLD+.5-a_code)/(b_code-a_code)
                        if a_code != b_code else .5)
            fraction = min(1.,max(0.,fraction))
            estimate = round(a["t_ns"]+fraction*(b["t_ns"]-a["t_ns"]))
            result.append({
                "phase":phase,
                "edge":"rising" if high_after else "falling",
                "bracket_ns":[a["t_ns"],b["t_ns"]],
                "estimate_ns":estimate,
                "wfi_before":a["wfi"],"wfi_after":b["wfi"],
                "electrical_angle_deg_estimate":
                    _angle_at([a,b],[a["t_ns"],b["t_ns"]],estimate),
                "time_precision":"WFI_BRACKET_ONLY_NOT_EXACT_ANALOG_EDGE",
            })
    return result


def audit(document):
    if (document.get("format")!="e62.sitl.native-wfi.v1" or
            document.get("scope")!="SIM_ONLY_UNCALIBRATED_OPEN_STAR_MODEL"):
        raise ValueError("Expected genuine native WFI trace schema")
    metadata=document.get("metadata",{})
    model=metadata.get("motor_model",{})
    if (metadata.get("host_guest_register_writes") is not False or
            model.get("electromagnetic_reciprocal") is not True or
            not model.get("pole_pairs") or
            model.get("physical_motor_calibrated") is not False):
        raise ValueError("Require source-attributed SIM_ONLY coupled model")
    samples=document.get("samples",[])
    events=document.get("events",[])
    if len(samples)<3 or not events:
        raise ValueError("Insufficient original Guest WFI/CAP1 events")
    times=[s["t_ns"] for s in samples]
    if any(type(t)!=int for t in times) or any(
            b<=a for a,b in zip(times,times[1:])):
        raise ValueError("WFI time must be strictly increasing")
    if any(s["wfi"]!=i for i,s in enumerate(samples,1)):
        raise ValueError("Missing consecutive Guest WFI evidence")
    if any(s.get("sampling_qualifier")!=
           "EXTERNAL_CLOCKED_CURRENT_CONTINUOUS_NO_AVERAGE" for s in samples):
        raise ValueError("Requires native clocked PWM to current/BEMF path")
    ke=model["bemf_constant_v_per_electrical_rad_s"]
    pole_pairs=model["pole_pairs"]
    max_bemf_error=0.0
    voltage_code_mismatches=0
    max_angle_step=0.
    for index,s in enumerate(samples):
        angle=s["electrical_rad"]
        omega=s["motor_rpm"]*TWO_PI/60.
        if not math.isfinite(angle) or not math.isfinite(omega):
            raise ValueError("Nonfinite model angular state")
        for phase,offset in enumerate(OFFSETS):
            theoretical=ke*pole_pairs*omega*math.sin(angle+offset)
            actual=s["bemf_phase_v"][phase]
            max_bemf_error=max(max_bemf_error,abs(theoretical-actual))
            if abs(theoretical-actual)>1e-6*max(1.,abs(theoretical)):
                raise ValueError("Guest fixture BEMF disagrees with motor equations")
            expected_code=round(4095*(BIAS_V+GAIN*actual)/VREF)
            if not 0<=expected_code<=4095:
                raise ValueError("BEMF fixture saturates; cannot audit threshold")
            if s["analog_adc_codes"][phase]!=expected_code:
                voltage_code_mismatches+=1
        if index:
            max_angle_step=max(max_angle_step, abs(math.degrees(
                _shortest_angle(samples[index-1]["electrical_rad"],angle))))
    if max_angle_step>=175:
        raise ValueError("WFI sampling cannot unwrap rotor phase reliably")
    crossings=_threshold_crossings(samples)
    grouped={}
    for event in events:
        if event.get("kind") not in ("CAP1_ACCEPTED","TIMG12_SERVICED"):
            raise ValueError("Unknown original Guest event kind")
        sector=event.get("sector")
        if type(sector)!=int or not 1<=sector<=24:
            raise ValueError("Invalid original native sector")
        grouped.setdefault(sector,{})[event["kind"]]=event
    cases=[]
    unbracketed=0
    wrong_order=0
    for sector,events_pair in sorted(grouped.items()):
        cap=events_pair.get("CAP1_ACCEPTED")
        svc=events_pair.get("TIMG12_SERVICED")
        if cap is None or svc is None:
            raise ValueError("Missing original CAP1 or TIMG12 service event")
        if cap["t_ns"] >= svc["t_ns"]:
            wrong_order+=1
        step=cap["guest_step_before"]
        if not 1<=step<=6 or svc["guest_step_after"]!=(step%6)+1:
            raise ValueError("Original Guest step route/order mismatch")
        selected=ORIGINAL_REL17_ROUTE[step][0]
        phase=(selected&3)-1
        rising=bool(selected&4)
        expected_edge="rising" if rising else "falling"
        # For expected analog threshold, prefer the observed model crossing
        # interval containing CAP1, then nearest preceding WFI bracket.
        matches=[c for c in crossings if c["phase"]==phase and
                 c["edge"]==expected_edge and
                 c["bracket_ns"][0]<=cap["t_ns"]<=c["bracket_ns"][1]]
        candidate=min(matches,key=lambda c:abs(c["estimate_ns"]-cap["t_ns"])) if matches else None
        if candidate is None:
            unbracketed+=1
        cases.append({
            "sector":sector,"original_guest_step_before":step,
            "expected_comparator_phase":phase,
            "expected_comparator_edge":expected_edge,
            "actual_cap1_ns":cap["t_ns"],
            "actual_timg12_service_ns":svc["t_ns"],
            "cap1_to_service_us":(svc["t_ns"]-cap["t_ns"])/1000.,
            "actual_cap1_electrical_angle_deg_estimated":
                _angle_at(samples,times,cap["t_ns"]),
            "actual_timg12_electrical_angle_deg_estimated":
                _angle_at(samples,times,svc["t_ns"]),
            "model_zero_crossing_bracket":candidate,
            "capture_has_matching_wfi_crossing_bracket":candidate is not None,
            "time_source":"ORIGINAL_ECAP1_TICKS_WHILE_WFI_ROTOR_IS_INTERPOLATED",
        })
    native=document.get("native_result") or {}
    return {
        "status":"DIAGNOSTIC_ONLY_NOT_ROTOR_STABILITY_QUALIFICATION",
        "profile":model["profile"],
        "original_elf_sha256":metadata.get("elf_sha256"),
        "guest_writes":False,
        "original_guest_wfi_samples":len(samples),
        "original_native_cap1_timg12_pairs":len(cases),
        "ordered_cap1_service_pairs":len(cases)-wrong_order,
        "max_model_bemf_formula_error_v":max_bemf_error,
        "analog_frontend_code_mismatches":voltage_code_mismatches,
        "model_to_fixture_bemf_consistency_pass":
            voltage_code_mismatches==0 and max_bemf_error<1e-6,
        "theoretical_sample_bracketed_crossings":len(crossings),
        "accepted_cap1_without_matching_wfi_threshold_bracket":unbracketed,
        "crossings_are_not_instantaneous_or_exhaustive":True,
        "first_16_crossings":crossings[:16],
        "sector_timing":cases,
        "max_abs_wfi_angle_step_deg":max_angle_step,
        "simulated_rotor_direction_reversals":
            native.get("significant_direction_reversals"),
        "original_guest_strict_rotor_gate":
            "NOT_WAIVED_NOT_PROVED_BY_THIS_AUDIT",
        "caveat":"WFI sampled BEMF and interpolation; CAP1/ISR actual simulated timestamps; missing crossing bracket is not proof of wrong edge",
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    evidence=audit(json.loads(args.trace.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n")
    print("PASS_G17_G18_NATIVE_BEMF_FORENSIC_REPORT "+
          json.dumps({k:v for k,v in evidence.items()
                      if k not in ("sector_timing","first_16_crossings")},sort_keys=True),
          flush=True)


if __name__=="__main__":
    main()
