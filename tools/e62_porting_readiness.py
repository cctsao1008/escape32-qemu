#!/usr/bin/env python3
"""Aggregate actual archived Original Guest FW porting evidence, never P1 waiver."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

ELF="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
FILES={
    "p0":"e62-porting-p0-mmio-verification.json",
    "p1":"e62-porting-p1-mmio-replay.json",
    "crc":"e62-dshot-crc-native-verdict.json",
    "neutral_fault":"e62-safety-qualification.json",
    "inflight_fault":"e62-native-p1-nfault.verdict.json",
}
RUNS={"p0":40632866806,"p1":40633019199,"crc":40631864430,
      "neutral_fault":40631864426,"inflight_fault":40631864583}

class EvidenceError(ValueError):
    pass

def must(condition,message):
    if not condition:
        raise EvidenceError(message)

def audit(sources):
    must(set(sources)==set(FILES),"missing independent Original Guest source")
    p0=sources["p0"]
    must(p0.get("status")=="PASS_SOURCE_MMIO_P0_SIM_ONLY" and
         p0.get("issues")==[],"p0 source MMIO not independently PASS")
    must(p0.get("original_elf_sha256")==ELF and
         p0.get("no_guest_intervention") is True and
         p0.get("source_clock")=="QEMU_CLOCK_VIRTUAL" and
         p0.get("hardware_qualified") is False and
         p0.get("p1_stability_not_tested") is True,
         "p0 guest source identity, virtual time or scope invalid")
    matched_cap=p0.get("matched_cap1_ack_guest_read")
    matched_timer=p0.get("matched_original_guest_timer_start_zero")
    err=p0.get("max_absolute_timer_deadline_error_ns")
    must(type(matched_cap)==int and matched_cap>0 and
         type(matched_timer)==int and matched_timer>0 and
         type(err) in (int,float) and 0<=err<=20,
         "p0 cap1/timer MMIO exact deadline contract incomplete")

    p1=sources["p1"]
    must(p1.get("status")=="PASS_MMIO_DIAGNOSTIC_NOT_P1_ACCEPTANCE"
         and p1.get("p0_p1_gates_unchanged") is True and
         p1.get("qualified_hardware") is False and
         p1.get("scope")=="SIM_ONLY","p1 scope or MMIO diagnostic wrong")
    cases=p1.get("cases")
    names=("smoke","gentle","direct20","steps")
    must(isinstance(cases,list) and len(cases)==4 and
         all(isinstance(c,dict) for c in cases) and
         {c.get("case") for c in cases}==set(names),
         "p1 cases absent or duplicated")
    by={c["case"]:c for c in cases}
    for n in names:
        c=by[n]
        e=c.get("timg12_virtual_deadline_error_ns")
        must(c.get("status")=="PASS_MMIO_SOURCE_CONTRACT" and
             c.get("issues")==[] and type(e) in (int,float) and abs(e)<=20,
             n+" lacks independent original Guest timer MMIO PASS")
        if n in ("smoke","gentle"):
            must(c.get("p1_unchanged_qualified") is True and
                 c.get("p1_unchanged_original_verdict")==
                 "PASS_P1_SIM_ONLY_OBSERVABILITY",
                 n+" missing original P1 motor PASS")
        else:
            must(c.get("p1_unchanged_qualified") is False and
                 c.get("p1_unchanged_original_verdict")==
                 "FAIL_P1_SIM_ONLY_OBSERVABILITY",
                 n+" original motor P1 FAIL was concealed")
            must(c.get("first_cap1_did_not_observably_arm_timer") is True
                 and c.get("first_then_second_capture_arm_pattern_observed")
                 is True,n+" first/second Guest CAP1 MMIO sequence not proven")

    crc=sources["crc"]
    must(crc.get("status")=="PASS_ORIGINAL_GUEST_PHYSICAL_BAD_CRC_REJECTED"
         and crc.get("issues")==[] and crc.get("scope")==
         "PHYSICAL_PA26_DSHOT600_SOURCE_CRC_AND_WWDT_FEED_ONLY"
         and crc.get("input_loss_watchdog_reset")=="OPEN_NOT_MODELED"
         and crc.get("physical_rotor_safety")=="NOT_QUALIFIED",
         "DShot source proof absent or false motor/watchdog claim")

    neutral=sources["neutral_fault"]
    must(neutral.get("status")==
         "PASS_SIM_ONLY_EXTERNAL_FAULT_IRQ_SHUTDOWN_ONLY"
         and neutral.get("issues")==[] and
         neutral.get("independent_cases_passed")==[
             "nfault","oc-u","oc-v","oc-w"] and
         neutral.get("scope")=="MODEL_ONLY_NATIVE_NEUTRAL_NOT_MOTOR_RUNNING"
         and neutral.get("real_power_stage")=="NOT_QUALIFIED",
         "neutral OC/nFAULT original Guest IRQ shutdown not qualified")

    inflight=sources["inflight_fault"]
    must(inflight.get("status")=="PASS_P1_NATIVE_IN_FLIGHT_NFAULT_SAFE_OFF"
         and inflight.get("qualified") is True and
         inflight.get("failures")==[] and
         inflight.get("source_fault_edges")==2 and
         inflight.get("source_latched_ost2_at_fault") is True and
         inflight.get("final_OST2_latched") is True and
         inflight.get("final_gate_off") is True and
         inflight.get("original_guest_never_halted_or_injected") is True and
         inflight.get("original_guest_crc_feeds",0)>0 and
         inflight.get("external_DShot_continuity",0)>0 and
         inflight.get("scope")==
         "SIM_ONLY_NFAULT_NEGATIVE_FAULT_RELEASE_NOT_RECOVERY" and
         inflight.get("automatic_rearm_and_flight_recovery_qualified") is False
         and inflight.get("electrical_hardware_qualified") is False,
         "in-flight no-WFI nFAULT safe-off incomplete or overclaimed")

    matrix=[
       {"id":"A01-A09","status":"VERIFIED_TESTED_SIM_ONLY_PORTING_CHAIN",
        "evidence":"original Guest P0 CAP1/MMIO/TIMG12, P1 MMIO source"},
       {"id":"A02","status":"VERIFIED_SIM_ONLY_VALID_AND_BAD_DSHOT_CRC",
        "evidence":"real PA26 wire, DMA, Guest callback, WWDT feed"},
       {"id":"A10-neutral","status":"VERIFIED_SIM_ONLY_NEUTRAL_FAULT_SHUTDOWN",
        "evidence":"PA22 nFAULT, OC U/V/W, OST, Guest MCPWM4 IRQ"},
       {"id":"A10-running","status":"VERIFIED_SIM_ONLY_RUNNING_NFAULT_SAFE_OFF",
        "evidence":"source 2 external edges, latch, no automatic rearm"},
       {"id":"A13","status":"GUEST_FIRST_CAP1_NO_REARM_OBSERVED_NOT_PRIVATE_RETURN"},
       {"id":"A14","status":"MOTOR_DYNAMICS_P1_FAIL_UNWAIVED",
        "cases":{"smoke":"PASS","gentle":"PASS","direct20":"FAIL","steps":"FAIL"}},
       {"id":"A11-A12","status":"PHYSICAL_ADC_ANALOG_POWER_AND_PROP_HW_REQUIRED"},
       {"id":"archive","status":"HISTORICAL_BINARY_SOURCE_FINGERPRINT_DRIFT_OPEN"},
       {"id":"input_loss","status":"WATCHDOG_INPUT_LOSS_AND_RECOVERY_NOT_QUALIFIED"}
    ]
    return {
       "schema":"e62-sitl-porting-readiness.v1",
       "status":"PASS_BOUNDED_SITL_PORTING_EVIDENCE_WITH_OPEN_ITEMS",
       "porting_complete":False,"hardware_qualified":False,
       "motor_p1_all_cases_qualified":False,
       "original_guest_elf_sha256":ELF,
       "guest_control_policy_changed":False,
       "motor_plant_changed":False,
       "p0_p1_gate_waiver":False,
       "historical_source_fingerprint_republished":False,
       "guest_capture_reject_private_return_observed":False,
       "p0_mmio":{"cap1_guest_read_chains":matched_cap,
                  "guest_timg12_zero_chains":matched_timer,
                  "max_virtual_timer_error_ns":err},
       "p1_mmio":{"cases":{n:{
                     "status":by[n]["status"],
                     "motor_p1_qualified":by[n]["p1_unchanged_qualified"],
                     "first_cap1_no_rearm":by[n][
                        "first_cap1_did_not_observably_arm_timer"],
                     "first_timer_deadline_error_ns":by[n][
                        "timg12_virtual_deadline_error_ns"]}
                        for n in names}},
       "matrix":matrix,
       "explicit_open":["P1 direct20/steps motor reverse",
          "ECX87 210KV 47V and APC 24x12E motor+prop load calibration",
          "Silicon CMPSS analog noise, ADC mapping and physical power stage",
          "Input-loss reset, watchdog, recovery and automatic rearm",
          "Historical G13B3 source fingerprint drift",
          "Hardware bring-up and complete product FW signoff"],
       "sources":{k:{"run_id":RUNS[k],"file":FILES[k]} for k in FILES}
    }

def to_markdown(out):
    lines=[
       "# E62 Original Guest — FW Porting SITL Evidence Packet",
       "",
       "Generated from five independent archived verdict files. No Guest or "
       "plant changes; not a full porting or HW signoff.",
       "",
       "**Status:** "+out["status"],
       "",
       "**Pinned Original ELF SHA256:** "+ELF,
       "",
       "## Verified and open scopes",
       "",
       "| ID | Verdict |",
       "|---|---|"
    ]
    for x in out["matrix"]:
        lines.append("| "+x["id"]+" | "+x["status"]+" |")
    lines.extend(["","## P0 Original Guest MMIO","",
                  "CAP1/ACK/Guest reads: "+
                  str(out["p0_mmio"]["cap1_guest_read_chains"]),
                  "",
                  "Guest TIMG12 START-to-ZERO matches: "+
                  str(out["p0_mmio"]["guest_timg12_zero_chains"]),
                  "",
                  "Maximum QEMU virtual timer mismatch: "+
                  str(out["p0_mmio"]["max_virtual_timer_error_ns"])+" ns",
                  "",
                  "## P1 independent MMIO versus motor verdict",
                  "","| Case | MMIO | Motor P1 | First CAP1 no timer rearm |",
                  "|---|---|---|---|"])
    for name,x in out["p1_mmio"]["cases"].items():
        lines.append("| "+name+" | "+x["status"]+" | "+
          ("PASS" if x["motor_p1_qualified"] else "FAIL")+
          " | "+str(x["first_cap1_no_rearm"])+" |")
    lines.extend(["","## Explicitly open",""])
    lines.extend("- "+x for x in out["explicit_open"])
    lines.extend(["","## Archived CI provenance",""])
    for key,item in out["sources"].items():
        lines.append("- "+key+" — "+
          "https://github.com/cctsao1008/escape32-qemu/actions/runs/"+
          str(item["run_id"])+" ("+item["file"]+")")
    lines.extend(["","The JSON output includes SHA256 of each consumed "
                  "artifact. Strict P0/P1 and hardware acceptance are unchanged.",""])
    return "\n".join(lines)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir",required=True,type=Path)
    parser.add_argument("--output-json",required=True,type=Path)
    parser.add_argument("--output-md",required=True,type=Path)
    args=parser.parse_args()
    sources={}; hashes={}
    for k,f in FILES.items():
        p=args.input_dir/f
        if not p.is_file():
            raise SystemExit("E62_READINESS_MISSING_SOURCE: "+str(p))
        blob=p.read_bytes()
        hashes[k]=hashlib.sha256(blob).hexdigest()
        sources[k]=json.loads(blob)
    try:
        report=audit(sources)
    except EvidenceError as e:
        raise SystemExit("E62_READINESS_FAIL_CLOSED: "+str(e))
    report["source_artifact_sha256"]=hashes
    args.output_json.parent.mkdir(parents=True,exist_ok=True)
    args.output_md.parent.mkdir(parents=True,exist_ok=True)
    args.output_json.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    args.output_md.write_text(to_markdown(report))
    print("E62_PORTING_READINESS "+json.dumps({
        "status":report["status"],"p0_mmio":report["p0_mmio"],
        "hardware_qualified":report["hardware_qualified"],
        "motor_p1_all_cases_qualified":
        report["motor_p1_all_cases_qualified"]},sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
