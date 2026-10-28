#!/usr/bin/env python3
"""P1 original Guest PA26 command-loss WWDT proof, never Host feed/reset.

Sources:
  1. exact native DShot600 QEMU PA26 waveform events from independent FC,
  2. actual Guest WWDT FEED MMIO timestamps from QEMU virtual clock,
  3. actual QEMU-clock WWDT expiry callback and RESET-safe-off log,
  4. Original ELF identity and no WFI/GDB/Guest writes.
The optional external FC stops at an active nonzero command; QEMU's
native clock and firmware continue unaided until the genuine Guest's
last WWDT feed expires. A model-only BOOTRST is NOT a hardware signoff.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p0_strict import parse_events,TraceError
from tools.native_dshot_scenario import SHA,load_native_scenario

BOOT=re.compile(r"ESC_SIM_WWDT_BOOTRST_REQUESTED: vns=(\d+) ")
WWDT_NS=1_000_000_000
TOLERANCE_NS=100

def audit(events,evidence,log,stages):
    faults=[]
    if evidence.get("original_elf_sha256")!=SHA:
        faults.append("PINNED_ORIGINAL_GUEST_ELF_MISMATCH")
    if (evidence.get("used_guest_wfi_or_gdb") is not False or
        evidence.get("host_guest_register_writes") is not False or
        evidence.get("synthetic_timed_bemf_enabled") is not False or
        evidence.get("link_loss_guest_writes") is not False):
        faults.append("HOST_INTERVENED_WITH_GUEST_OR_SYNTHETIC_MOTOR")
    if evidence.get("status")!="OBSERVED_P1_GUEST_WWDT_INPUT_LOSS_SIM_ONLY":
        faults.append("NO_ACTUAL_NATIVE_RUNNING_INPUT_LOSS_PROBE")
    if not (evidence.get("link_loss_wwdt_running_on_disconnect") is True
            and evidence.get("link_loss_bootrst_observed") is True
            and evidence.get("link_loss_original_firmware_unchanged") is True):
        faults.append("NO_SOURCE_OWNED_GUEST_WWDT_RUNNING_AND_BOOTRST")
    auto=evidence.get("autonomous_dshot") or {}
    sent=evidence.get("link_loss_last_frame")
    if not (type(sent) is int and sent>0 and sent<sum(x[0] for x in stages)
            and auto.get("sent")==sent and
            auto.get("target_frames")==sent and
            evidence.get("configured_dshot_frames")==sent):
        faults.append("NO_PRECISE_EXTERNAL_FC_STOP_FRAME")
    if not (type(auto.get("last_dshot")) is int and
            auto.get("last_dshot")>0 and
            evidence.get("link_loss_last_dshot")==auto.get("last_dshot")):
        faults.append("LINK_LOSS_NOT_AFTER_POSITIVE_PHYSICAL_DSHOT")
    if not (evidence.get("original_guest_after") or {}).get(
            "valid_frame_feeds",0)>0:
        faults.append("GUEST_VALID_DSHOT_WWDT_FEED_NOT_PROVEN")
    commands=[e for e in events if e["kind"]=="DSHOT"]
    feeds=[e for e in events if e["kind"]=="WWDT_FEED"]
    boot=[int(x) for x in BOOT.findall(log)]
    if (not commands or type(sent) is not int or
        len(commands)!=sent or
        [e["data"][0] for e in commands]!=list(range(sent))):
        faults.append("EXTERNAL_DSHOT_SOURCE_NOT_EXACTLY_CUTOFF")
    if not feeds:
        faults.append("NO_GENUINE_GUEST_WWDT_FEED_MMIO")
    if len(boot)!=1:
        faults.append("NO_EXACTLY_ONE_HARDWARE_MODEL_BOOTRST")
    if "PB13 LOW; PWM frozen; resetcause=0x0e" not in log:
        faults.append("NO_NATIVE_POWER_GATE_SAFE_OFF_BEFORE_RESET")
    if feeds and commands:
        if not feeds[0]["vns"]>=commands[0]["vns"]:
            faults.append("WWDT_FEED_PRECEDES_EXTERNAL_SOURCE")
        if any(x["data"][1]&0x77!=0x30 for x in feeds):
            # Period 2^15, prescaler 1, 0% window: ensure no host
            # drives a shorter artificial expiration in QEMU.
            faults.append("WWDT0_ORIGINAL_POLICY_NOT_NOMINAL_ONE_SECOND")
        if not all(feeds[i]["data"][0]==i+1 for i in range(len(feeds))):
            faults.append("WWDT_FEED_SEQUENCE_NOT_GUEST_OWNED")
    last_feed=feeds[-1] if feeds else None
    last_frame=commands[-1] if commands else None
    expire_ns=boot[0] if len(boot)==1 else None
    residual=(expire_ns-last_feed["vns"]-WWDT_NS
              if expire_ns is not None and last_feed is not None else None)
    if residual is None or abs(residual)>TOLERANCE_NS:
        faults.append("GUEST_WWDT_EXPIRY_NOT_ONE_SECOND_AFTER_LAST_FEED")
    if expire_ns is not None and last_frame is not None and (
        expire_ns<=last_frame["vns"]):
        faults.append("BOOTRST_PRECEDES_DISCONNECT")
    return {
        "status":"PASS_P1_NATIVE_GUEST_INPUT_LOSS_WWDT_BOOTRST_SIM_ONLY"
                 if not faults else "FAIL_P1_NATIVE_GUEST_INPUT_LOSS_WWDT",
        "issues":faults,"scope":"ORIGINAL_GUEST_NO_WFI_HARD_PA26_SIGNAL_LOSS",
        "no_host_guest_writes":True,"source_clock":"QEMU_CLOCK_VIRTUAL",
        "original_elf_sha256":SHA,"external_dshot_frames":len(commands),
        "original_guest_wwdt_feed_writes":len(feeds),
        "last_fc_dshot_virtual_ns":(last_frame["vns"] if last_frame else None),
        "last_original_guest_wwdt_feed_virtual_ns":(
            last_feed["vns"] if last_feed else None),
        "model_wwdt_bootrst_virtual_ns":expire_ns,
        "model_wwdt_nominal_period_ns":WWDT_NS,
        "model_wwdt_deadline_error_ns":residual,
        "physical_power_stage_qualified":False,
        "real_lfclk_qualified":False,"input_loss_silicon_qualified":False,
        "automatic_motor_restart_qualified":False,
        "motor_p1_startup_reversal_qualified":False,
        "original_fw_policy_changed":False,"motor_plant_changed":False,
        "diagnostic_note":"QEMU 32768Hz LFCLK assumption and optional "
            "BOOTRST; not real AM13E silicon timing, hardware Gate driver "
            "output or motor flight safety"
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--evidence",type=Path,required=True)
    p.add_argument("--qemu-log",type=Path,required=True)
    p.add_argument("--scenario",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    try:
        stages,meta=load_native_scenario(a.scenario)
        with a.events.open(errors="replace") as f:
            events=parse_events(f)
        run=json.loads(a.evidence.read_text())
        result=audit(events,run,a.qemu_log.read_text(errors="replace"),stages)
        result["scenario_sha256"]=meta["sha256"]
    except (OSError,ValueError,TypeError,TraceError,KeyError) as exc:
        result={"status":"FAIL_P1_NATIVE_GUEST_INPUT_LOSS_WWDT",
                "issues":[type(exc).__name__+": "+str(exc)],
                "scope":"ORIGINAL_GUEST_NO_WFI_HARD_PA26_SIGNAL_LOSS",
                "input_loss_silicon_qualified":False}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print("E62_P1_GUEST_INPUT_LOSS "+json.dumps({
        k:result.get(k) for k in
        ("status","external_dshot_frames",
         "original_guest_wwdt_feed_writes",
         "model_wwdt_deadline_error_ns","issues")},sort_keys=True))
    return (0 if result["status"] ==
            "PASS_P1_NATIVE_GUEST_INPUT_LOSS_WWDT_BOOTRST_SIM_ONLY" else 1)

if __name__=="__main__":
    raise SystemExit(main())
