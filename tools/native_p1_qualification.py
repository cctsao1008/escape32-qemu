#!/usr/bin/env python3
"""Native P1 report: exact independent FC input, rotor response, analog and CI cost.

Source: QEMU virtual-clock E62_P0_EVENT and completed original-Guest
no-WFI run JSON. This does NOT qualify propeller, 12S, thermal/semiconductor
loss, real ESC sensor calibration, or signal-loss fault recovery.
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_dshot_scenario import load_native_scenario
from tools.native_p0_strict import parse_events, TraceError


def dshot_value(permille):
    if permille == 0:
        return 0
    numerator=1999*permille
    quotient,remainder=divmod(numerator,1000)
    return 48+quotient+(remainder>500 or
                        (remainder==500 and (quotient&1)!=0))


def commands_for_scenario(stages):
    """Deterministic independent oracle for QEMU DShot target mapping."""
    for stage_idx,(duration,start,end,update) in enumerate(stages):
        for local_ms in range(duration):
            stepped=(local_ms//update)*update
            v=start+(end-start)*stepped//duration
            yield stage_idx,dshot_value(v)


def analyze(events,evidence,stages,meta):
    failures=[]
    if evidence.get("live_throttle_used") is True or any(
        e["kind"]=="THROT_SET" for e in events
    ):
        failures.append("MANUAL_LIVE_THROTTLE_NOT_REPRODUCIBLE_JSON_CASE")
    actual=[e for e in events if e["kind"]=="DSHOT"]
    expected=list(commands_for_scenario(stages))
    if len(actual)!=len(expected):
        failures.append("DSHOT_SOURCE_FRAME_COUNT_MISMATCH")
    # The very FIRST QEMU virtual-timer callback can dispatch late
    # because the guest CPU is executing its initial TB. Its next
    # deadline is source-owned and absolute (start_ns+1ms), so use the
    # SECOND frame to establish this deadline epoch. Preserve exact
    # nanosecond equality for every later 1kHz frame; the first
    # callback must still leave at least 30us before the next DShot
    # frame (16 x 1.667us wire bits + idle). Never relax a lost frame,
    # bad throttle command, stage mismatch or accumulated clock drift.
    clock_epoch=(actual[1]["vns"]-1000000 if len(actual)>1 else None)
    first_frame_lateness_ns=(
        actual[0]["vns"]-clock_epoch if clock_epoch is not None else None)
    source_first_gap_ns=(
        actual[1]["vns"]-actual[0]["vns"] if len(actual)>1 else None)
    # Original CI artifact shows 11 actual 2ns QEMU TB dispatch
    # quantizations among 3000 source frames. Require bounded 100ns
    # scheduling lateness, far below the 1.667us DShot600 bit time.
    # Frame values, stage order, source count remain *exact*.
    # This is QEMU instruction-dispatch tolerance, NOT guest motor
    # angle/PWM/BEMF timing tolerance or a relaxed arming window.
    dispatch_budget_ns=100
    max_steady_dispatch_lateness_ns=0
    steady_dispatch_late_count=0
    first_mismatch=None
    for idx,(event,want) in enumerate(zip(actual,expected)):
        got=event["data"]
        value_ok=(got[0]==idx and got[1]==want[0] and
                  got[2]==want[1] and got[3]==0 and got[4]==0)
        dispatch_ns=(event["vns"]-(clock_epoch+idx*1000000)
                     if clock_epoch is not None else None)
        if idx>0 and dispatch_ns is not None:
            max_steady_dispatch_lateness_ns=max(
                max_steady_dispatch_lateness_ns,abs(dispatch_ns))
            if dispatch_ns:
                steady_dispatch_late_count+=1
        time_ok=(clock_epoch is not None and
                 (0<=dispatch_ns<=dispatch_budget_ns if idx>0 else
                  0<=first_frame_lateness_ns<=970000))
        if not value_ok or not time_ok:
            first_mismatch={
                "frame_index":idx,"expected_stage":want[0],
                "observed_stage":got[1],"expected_dshot_value":want[1],
                "observed_dshot_value":got[2],
                "observed_virtual_ns":event["vns"],
                "expected_deadline_virtual_ns":(
                    clock_epoch+idx*1000000 if clock_epoch is not None
                    else None),
                "reason":("DSHOT_VALUE_OR_FRAME_INDEX" if not value_ok
                          else "SOURCE_VIRTUAL_CLOCK"),
            }
            failures.append("DSHOT_VIRTUAL_CLOCK_OR_VALUE_MISMATCH")
            break
    if evidence.get("native_dshot_scenario",{}).get("sha256")!=meta["sha256"]:
        failures.append("EVIDENCE_SCENARIO_SHA_MISMATCH")
    if (evidence.get("original_elf_sha256")!=meta["original_elf_sha256"] or
        evidence.get("host_guest_register_writes") is not False or
        evidence.get("used_guest_wfi_or_gdb") is not False or
        evidence.get("synthetic_timed_bemf_enabled") is not False):
        failures.append("ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN")
    if (evidence.get("configured_dshot_frames")!=len(expected) or
        (evidence.get("autonomous_dshot") or {}).get("sent")!=len(expected)):
        failures.append("SIMULATOR_TRANSMITTER_INCOMPLETE")

    active_indices=[i for i,(_,value) in enumerate(expected) if value!=0]
    if not active_indices or tzero is None:
        failures.append("NO_POSITIVE_DSHOT_COMMAND")
    onset=(clock_epoch+active_indices[0]*1000000
           if active_indices and clock_epoch is not None else None)
    offset=(clock_epoch+(active_indices[-1]+1)*1000000
            if active_indices and clock_epoch is not None else None)
    rotor=[e for e in events if e["kind"]=="ROTOR"]
    positive_rotor=[e for e in rotor if onset is not None and
                    onset<=e["vns"]<offset]
    active_rpms=[e["data"][0]/1000 for e in positive_rotor]
    peak=max((abs(x) for x in active_rpms),default=0)
    first_motion=next((e["vns"] for e in positive_rotor
                       if abs(e["data"][0])>=50000),None)
    first_90=next((e["vns"] for e in positive_rotor
                   if peak>=50 and abs(e["data"][0])/1000>=peak*.90),None)
    peak_e=next((e for e in positive_rotor
                 if abs(e["data"][0])/1000==peak),None)
    if peak<50:
        failures.append("NO_50RPM_SOURCE_STARTUP_RESPONSE")
    sign={1 if r>0 else -1 for r in active_rpms if abs(r)>=50}
    significant_changes=[]
    preceding_sign=None
    for rotor_sample in positive_rotor:
        rpm=rotor_sample["data"][0]/1000
        if abs(rpm)<50:
            continue
        observed_sign=1 if rpm>0 else -1
        if preceding_sign is not None and observed_sign!=preceding_sign:
            significant_changes.append({
                "virtual_ns":rotor_sample["vns"],
                "relative_to_first_positive_ms":round(
                    (rotor_sample["vns"]-onset)/1e6,3),
                "rpm":rpm,
            })
        preceding_sign=observed_sign
    if significant_changes:
        failures.append("STARTUP_SIGNIFICANT_DIRECTION_REVERSAL")
    last_rotor=rotor[-1]["data"][0]/1000 if rotor else None
    # Verify real, source-ordered feedback in positive-command interval.
    source_pairs=[e for e in events if e["kind"]=="PWM_PAIR" and
                  onset is not None and onset<=e["vns"]<offset]
    source_cap1_ack=[e for e in events if e["kind"]=="CAP1_ACK" and
                     onset is not None and onset<=e["vns"]<offset]
    source_t12_ack=[e for e in events if e["kind"]=="TIMG12_ACK" and
                    onset is not None and onset<=e["vns"]<offset]
    if (len(source_pairs)<12 or len(source_cap1_ack)<12 or
        len(source_t12_ack)<12):
        # A genuine six-step sensorless start MUST achieve a sequence
        # of original Guest-acknowledged interrupts and six-pad sectors,
        # not just CRC+throttle or a command speed estimate.
        failures.append("INSUFFICIENT_ORIGINAL_GUEST_CLOSED_LOOP_AFTER_ARM")
    if rotor and onset is not None and any(
        abs(e["data"][0])>=50000 for e in rotor if e["vns"]<onset):
        failures.append("UNCOMMANDED_ROTOR_SPEED_BEFORE_POSITIVE_DSHOT")

    bemf=[e for e in events if e["kind"]=="BEMF_FRONTEND"]
    oc=[e for e in events if e["kind"]=="OC_FRONTEND"]
    if len(bemf)!=len(rotor) or len(oc)!=len(rotor):
        failures.append("FRONTEND_SAMPLE_COUNT_NOT_ROTOR_CLOCKED")
    bemf_invalid=sum(
        1 for e in bemf if not all(0<=x<=4095 for x in e["data"][:3]) or
        not 0<=e["data"][3]<3 or not 0<=e["data"][4]<=4095 or
        e["data"][5] not in (0,1))
    if bemf_invalid:
        failures.append("BEMF_FRONTEND_INVALID_OR_MUX_UNSELECTED")
    oc_invalid=sum(
        1 for e in oc if not all(0<=x<=4095 for x in e["data"][:3]) or
        e["data"][3]&~7 or e["data"][4]&~7 or e["data"][5]&~7)
    if oc_invalid:
        failures.append("OC_FRONTEND_INVALID_SAMPLE_FORMAT")
    # Physical OC must be ready in a sustained positive command interval,
    # not simply have an end-of-test healthy readback.
    active_oc=[e for e in oc if onset is not None and
               onset<=e["vns"]<offset]
    active_ready=sum(1 for e in active_oc if e["data"][3]==7 and
                     e["data"][4]==7 and e["data"][5]==0)
    if not active_oc or active_ready < .95*len(active_oc):
        failures.append("OC_FRONTEND_NOT_VALID_READY_DURING_DRIVE")
    if any(e["data"][5] for e in active_oc):
        failures.append("OC_PHYSICAL_COMPARATOR_ACTUALLY_TRIPPED")
    cmp_events=[e for e in events if e["kind"]=="CMP_FILTER"]
    if not cmp_events:
        failures.append("NO_ORIGINAL_BEMF_COMPARATOR_FILTER_TRANSITIONS")
    if (evidence.get("native_motor") or {}).get("ost3_latch_activations")!=0:
        failures.append("NATIVE_HARDWARE_OST3_AT_END")
    if (evidence.get("native_motor") or {}).get("model_fault")!=0:
        failures.append("MOTOR_MODEL_ERROR")

    wall=evidence.get("qemu_run_wall_elapsed_s")
    elapsed=(evidence.get("autonomous_dshot") or {}).get("elapsed_ns")
    performance=None
    if isinstance(wall,(int,float)) and math.isfinite(wall) and wall>0 and (
        isinstance(elapsed,int) and elapsed>0):
        performance={
            "host_wall_s":wall,
            "virtual_s":elapsed/1e9,
            "virtual_seconds_per_host_second":round(elapsed/1e9/wall,6),
            "native_physics_ticks_per_host_second":round(
                (evidence.get("native_motor") or {}).get(
                    "native_1us_physics_ticks",0)/wall,1),
            "qemu_log_bytes":evidence.get("qemu_log_bytes"),
            "includes_guest_boot_and_qtest_monitoring":True,
            "not_an_absolute_cpu_benchmark":True,
        }
    else:
        failures.append("QEMU_VIRTUAL_TO_WALL_PERFORMANCE_UNAVAILABLE")

    return {
        "status":"PASS_P1_SIM_ONLY_OBSERVABILITY" if not failures else
                 "FAIL_P1_SIM_ONLY_OBSERVABILITY",
        "qualified":not failures,
        "scope":"NO_WFI_ORIGINAL_GUEST_UNCALIBRATED_24V_NO_PROPELLER",
        "unwaived_observability_failures":list(dict.fromkeys(failures)),
        "scenario_sha256":meta["sha256"],
        "dshot_frames":len(actual),
        "source_expected_frames":len(expected),
        "dshot_first_callback_lateness_ns":first_frame_lateness_ns,
        "dshot_first_to_second_frame_gap_ns":source_first_gap_ns,
        "dshot_source_absolute_timer_epoch_ns":clock_epoch,
        "dshot_first_mismatch":first_mismatch,
        "dshot_from_second_frame_bounded_1khz":first_mismatch is None,
        "dshot_steady_dispatch_lateness_budget_ns":dispatch_budget_ns,
        "dshot_max_observed_dispatch_error_ns":max_steady_dispatch_lateness_ns,
        "dshot_steady_frames_nonzero_dispatch_ns":steady_dispatch_late_count,
        "source_guest_closed_loop_pwm_pairs":len(source_pairs),
        "source_guest_cap1_w1c_ack":len(source_cap1_ack),
        "source_guest_timg12_w1c_ack":len(source_t12_ack),
        "significant_rotor_direction_changes":len(significant_changes),
        "significant_rotor_direction_change_samples":significant_changes[:15],
        "input_positive_start_virtual_ns":onset,
        "input_positive_end_virtual_ns":offset,
        "first_observed_50rpm_delay_ms":(
            (first_motion-onset)/1e6 if first_motion is not None else None),
        "time_to_90_percent_OF_THIS_TEST_peak_ms":(
            (first_90-onset)/1e6 if first_90 is not None else None),
        "peak_abs_rpm_in_positive_window":peak,
        "peak_abs_rpm_virtual_ns":peak_e["vns"] if peak_e else None,
        "last_rotor_rpm_after_declared_coast":last_rotor,
        "active_speed_signs_above_50rpm":sorted(sign),
        "positive_window_rotor_samples":len(positive_rotor),
        "bemf_samples":len(bemf),
        "bemf_invalid_samples":bemf_invalid,
        "physical_comparator_filter_events":len(cmp_events),
        "oc_samples":len(oc),
        "oc_invalid_samples":oc_invalid,
        "oc_active_fully_ready_valid_count":active_ready,
        "oc_active_window_samples":len(active_oc),
        "performance":performance,
        "startup_rpm_target_customer_qualified":False,
        "propeller_and_12s_power_qualified":False,
        "signal_loss_and_fault_recovery_qualified":False,
        "silicon_analog_frontend_calibrated":False,
        "disclaimer":"Peak 90% refers to observed SIM_ONLY scenario peak, not 8800rpm or a physical customer response requirement",
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--scenario",type=Path,required=True)
    p.add_argument("--evidence",type=Path,required=True)
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    try:
        stages,meta=load_native_scenario(a.scenario)
        data=json.loads(a.evidence.read_text())
        with a.events.open(errors="replace") as stream:
            report=analyze(parse_events(stream),data,stages,meta)
    except (OSError,ValueError,TraceError,KeyError,TypeError) as exc:
        report={"status":"FAIL_P1_SIM_ONLY_OBSERVABILITY",
                "qualified":False,
                "unwaived_observability_failures":["INVALID_OR_MISSING_INPUT"],
                "error":type(exc).__name__+": "+str(exc)}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("E62_NATIVE_P1_QUALIFICATION "+json.dumps(report,sort_keys=True))
    if not report["qualified"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
