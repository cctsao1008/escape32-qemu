#!/usr/bin/env python3
"""Original ELF no-WFI live Python ESC-SIM CLI integration via QEMU source FC.

The only QTest writes outside startup are to QEMU's non-silicon
external-flight-controller throttle fields at 0x5ffea134/0x5ffea130.
Never inject throttle into Guest RAM/UART, bypass DShot or stop Guest.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.e62_sim_cli import E62SimConsole
from tools.sitl_autonomous_transport import AUTO_BASE,REG,read_auto
from tools.native_p0_strict import parse_events


def until_frame(console,target,deadline):
    last=0
    while time.monotonic()<deadline:
        if not console.active:
            raise RuntimeError("QEMU exited before virtual DShot frames complete")
        q=console.qtest
        last=q.read(AUTO_BASE+REG["sent"])
        if last>=target:
            return last
        if q.read(AUTO_BASE+REG["status"])&4:
            raise RuntimeError("FC QEMU source error")
        time.sleep(.1)
    raise TimeoutError(f"no source progress toward frame {target}, last={last}")


def run(args):
    c=E62SimConsole(qemu=args.qemu,elf=args.elf,cfg_flash=args.cfg_flash,
                    scenario=ROOT/"scenarios/e62-native-p0-smoke.json",
                    artifacts=args.artifacts)
    try:
        c._launch()
        deadline=time.monotonic()+args.timeout
        before=until_frame(c,1650,deadline)
        c.do_throt("10.0")
        # Check the actual source FC virtual MMIO fields, not just
        # CLI stdout. We must see at least 80 real PA26 frames sent
        # while the override is active.
        q=c.qtest
        if q.read(AUTO_BASE+REG["live_override"])!=1 or (
            q.read(AUTO_BASE+REG["live_permille"])!=100):
            raise AssertionError("Live 10% override did not reach QEMU FC port")
        after=until_frame(c,before+80,deadline)
        c.do_throt("auto")
        if q.read(AUTO_BASE+REG["live_override"])!=0:
            raise AssertionError("Live FC override was not released")
        until_frame(c,c.meta["dshot_frames"],deadline)
        while not (q.read(AUTO_BASE+REG["status"])&2):
            if time.monotonic()>deadline:
                raise TimeoutError("Native FC end of scenario not reached")
            time.sleep(.05)
        evidence=c._finish()
        with Path(evidence["p0_event_trace_path"]).open() as inp:
            events=parse_events(inp)
        controls=[e for e in events if e["kind"]=="THROT_SET"]
        overridden=[e for e in events if e["kind"]=="DSHOT" and e["data"][3]==1]
        resumed=[e for e in events if e["kind"]=="DSHOT" and
                 e["data"][3]==0 and e["data"][0]>after]
        if len(controls)!=3 or not overridden or not resumed:
            raise AssertionError("Missing QEMU source-owned live changes/frames")
        if not any(e["data"][2]==248 for e in overridden):
            # 10% permille=100 maps to 48 + nearest-even(199.9)=248
            raise AssertionError("Live 10 percent not applied in original PA26 source frames")
        if evidence["original_guest_after"].get("valid_frame_feeds",0)<1:
            raise AssertionError("Original Guest never accepted a physical CRC frame")
        if evidence["native_motor"].get("model_fault")!=0:
            raise AssertionError("Native motor model failed during live external control")
        report={
            "status":"PASS_NATIVE_PYTHON_CONSOLE_LIVE_FC_SOURCE",
            "qualified":True,
            "source_event_controls":len(controls),
            "actual_overridden_dshot_frames":len(overridden),
            "auto_resumed_frame_count":len(resumed),
            "original_guest_crc_accepted_frames":evidence[
                "original_guest_after"]["valid_frame_feeds"],
            "original_guest_firmware_changed":False,
            "no_wfi_or_gdb":True,
            "motor_model_fault":evidence["native_motor"]["model_fault"],
            "source_trace_path":evidence["p0_event_trace_path"],
            "strict_rotor_or_hardware_qualification":False,
        }
        a=args.artifacts/"e62-native-console-live-integration.json"
        a.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
        print("E62_PYTHON_CLI_LIVE_QEMU "+json.dumps(report,sort_keys=True))
        return report
    finally:
        c._teardown()


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--qemu",type=Path,required=True)
    p.add_argument("--elf",type=Path,required=True)
    p.add_argument("--cfg-flash",type=Path,required=True)
    p.add_argument("--artifacts",type=Path,default=ROOT/"artifacts")
    p.add_argument("--timeout",type=int,default=240)
    a=p.parse_args()
    a.artifacts.mkdir(parents=True,exist_ok=True)
    run(a)


if __name__=="__main__":
    main()
