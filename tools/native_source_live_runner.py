#!/usr/bin/env python3
"""Opt-in No-WFI Original Guest live WebGUI without changing the proven probe.

Runs the EXISTING tests/e62_autonomous_native_motor_probe.py as a child,
watches only its stderr source-event file, and publishes bounded read-only
frames via tools.sitl_live localhost SSE. Does NOT open QTest or GDB.
A failed GUI adapter never writes to the Guest or alters native simulation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.native_source_trace import (
    ELF, FORMAT, NativeSourceReducer, SourceTraceError, read_source_line, convert
)
from tools.sitl_live import SitlLiveServer

def watch_log(path, proc, hub, errors, *, poll_s=0.05):
    """Tail a growing regular file; QEMU source virtual time is NEVER stepped."""
    reducer=NativeSourceReducer()
    try:
        while not path.is_file():
            if proc.poll() is not None:
                raise SourceTraceError("No QEMU source log from existing probe")
            time.sleep(poll_s)
        with path.open(encoding="utf-8",errors="replace") as source:
            while True:
                line=source.readline()
                if line:
                    event=read_source_line(line)
                    if event is not None:
                        frame=reducer.ingest(event)
                        if frame is not None:
                            hub.publish(frame["sample"],frame["events"])
                elif proc.poll() is not None:
                    break
                else:
                    time.sleep(poll_s)
        if reducer.total_samples==0:
            raise SourceTraceError("No native ROTOR/BEMF_FRONTEND from QEMU")
    except Exception as exc:
        errors.append(type(exc).__name__+": "+str(exc))
    return reducer.finish()

def run(args):
    if hashlib.sha256(args.elf.read_bytes()).hexdigest()!=ELF:
        raise SourceTraceError("Pinned Original ESCape32 Rel17.3 ELF changed")
    if not args.qemu.is_file() or not args.cfg_flash.is_file():
        raise FileNotFoundError("Need source-built QEMU and SIM_ONLY CFG")
    if not args.scenario.is_file():
        raise FileNotFoundError(args.scenario)
    if args.artifact.suffix!=".json":
        raise ValueError("Native probe artifact must end with .json")
    if args.hold and not sys.stdin.isatty():
        raise ValueError("--hold requires interactive terminal")
    log=args.artifact.with_suffix(".qemu.log")
    events=args.artifact.with_suffix(".p0.events.log")
    offline=args.source_trace_output or args.artifact.with_suffix(".source-trace.json")
    for p in (args.artifact,log,events,offline):
        if p.exists():
            raise FileExistsError(
                "Refusing stale No-WFI source artifact; choose new --artifact: "+str(p))
    args.artifact.parent.mkdir(parents=True,exist_ok=True)
    offline.parent.mkdir(parents=True,exist_ok=True)
    server=SitlLiveServer(port=args.port).start()
    server.hub.begin(NativeSourceReducer().metadata)
    print("E62_NATIVE_NO_WFI_SOURCE_LIVE_URL "+server.url,flush=True)
    cmd=[
        sys.executable,str(ROOT/"tests"/"e62_autonomous_native_motor_probe.py"),
        "--qemu",str(args.qemu.resolve()),
        "--elf",str(args.elf.resolve()),
        "--cfg-flash",str(args.cfg_flash.resolve()),
        "--scenario",str(args.scenario.resolve()),
        "--artifact",str(args.artifact.resolve()),
        "--wall-timeout-s",str(args.wall_timeout_s)
    ]
    if args.link_loss_last_frame:
        cmd.extend(["--link-loss-last-frame",str(args.link_loss_last_frame)])
    if args.switch_focus_window_ms:
        cmd.extend(["--switch-focus-window-ms",
                    args.switch_focus_window_ms])
    proc=None;errors=[];summary=None;code=1
    try:
        proc=subprocess.Popen(cmd,cwd=str(ROOT))
        watcher=threading.Thread(target=lambda: errors.append(
            ("_SUMMARY_",watch_log(log,proc,server.hub,errors))),
            name="e62-native-source-log-readonly",daemon=True)
        watcher.start()
        code=proc.wait()
        watcher.join(timeout=10)
        if watcher.is_alive():
            errors.append("Source log reader failed to drain after probe exit")
        for item in errors:
            if isinstance(item,tuple) and item[0]=="_SUMMARY_":
                summary=item[1]
        errors=[e for e in errors if isinstance(e,str)]
        # Produce a FULL offline source JSON, unaffected by live ring truncation.
        if events.is_file() and events.stat().st_size:
            try:
                with events.open(encoding="utf-8",errors="replace") as stream:
                    data=convert(stream)
                data["capture_state"]=(
                    "SOURCE_LOG_COMPLETE" if code==0 and not errors
                    else "PARTIAL_PROBE_FAIL")
                if args.artifact.is_file():
                    report=json.loads(args.artifact.read_text())
                    data["native_result"]={
                        "probe_status":report.get("status"),
                        "not_a_strict_p1_motor_pass":True,
                    }
                offline.write_text(json.dumps(data,allow_nan=False,
                                              separators=(",",":"))+"\n")
                print("E62_NATIVE_NO_WFI_OFFLINE_SOURCE_JSON "+
                      str(offline),flush=True)
            except Exception as exc:
                errors.append("Offline adapter: "+type(exc).__name__+": "+str(exc))
        if code==0 and not errors:
            print("E62_NATIVE_SOURCE_DASHBOARD_READ_ONLY_PASS "+
                  json.dumps(summary,sort_keys=True),flush=True)
        else:
            print("E62_NATIVE_SOURCE_DASHBOARD_INCOMPLETE "+
                  json.dumps({"probe_exit_code":code,"errors":errors},
                             sort_keys=True),flush=True)
        server.hub.finish(
            native_result={
                "probe_exit_code":code,
                "adapter_summary":summary,
                "adapter_errors":errors,
                "no_wfi_source_is_not_motor_strict_pass":True,
            },
            error_type=("NativeProbeFailed" if code else
                        "SourceAdapterIncomplete" if errors else None))
        if args.hold:
            print("Read-only WebGUI retained; press Ctrl-C to close",flush=True)
            try:
                while True:time.sleep(0.25)
            except KeyboardInterrupt:
                pass
        return code if code else (1 if errors else 0)
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
        server.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--qemu",type=Path,required=True)
    p.add_argument("--elf",type=Path,required=True)
    p.add_argument("--cfg-flash",type=Path,required=True)
    p.add_argument("--scenario",type=Path,required=True)
    p.add_argument("--artifact",type=Path,required=True)
    p.add_argument("--source-trace-output",type=Path)
    p.add_argument("--port",type=int,default=8765)
    p.add_argument("--hold",action="store_true")
    p.add_argument("--link-loss-last-frame",type=int,default=0)
    p.add_argument("--switch-focus-window-ms",default=None,
                   help="Optional 1..50ms source-only AQ/DB switching focus "
                        "START:END virtual ms; default off")
    p.add_argument("--wall-timeout-s",type=int,default=180)
    args=p.parse_args()
    if not 0<=args.port<=65535 or not 30<=args.wall_timeout_s<=600:
        p.error("Invalid port or wall deadline")
    try:
        return run(args)
    except (ValueError,OSError,SourceTraceError) as exc:
        print("E62_NATIVE_SOURCE_DASHBOARD_FAIL "+
              type(exc).__name__+": "+str(exc),file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
