#!/usr/bin/env python3
"""E62 diagnostic ONLY: preboot QEMU-clock FC stimulus, passive original Guest.

Not a replacement for production-like P0/P1; no Guest SRAM/IRQ/MMIO writes,
no QTest socket, no GDB/WFI, no wall-time-derived virtual time stepping.
Only the opt-in machine fixture starts the original virtual PA26 wire timer.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.native_dshot_scenario import load_native_scenario
from tools.native_source_energy_audit import parse_source
from tools.native_source_trace import ELF

SMOKE = [(1500, 0, 0, 1), (1000, 0, 200, 5),
         (300, 200, 200, 1), (200, 0, 0, 1)]
LAST_DSHOT = 2999
DSHOT = re.compile(r"\bkind=DSHOT a=(\d+)\b")
MAX_LOG_BYTES = 64 * 1024 * 1024

def validate_scenario(path):
    stages, metadata = load_native_scenario(path)
    if stages != SMOKE or metadata["dshot_frames"] != 3000:
        raise ValueError("Diagnostic preboot FC machine contract requires exact pinned P0 smoke")
    return metadata

def passive_until_final_frame(log_path, proc, *, wall_timeout_s):
    """Single sequential file reader: never interacts with running QEMU."""
    deadline = time.monotonic() + wall_timeout_s
    expected_index = 0
    with log_path.open(encoding="utf-8", errors="replace") as stream:
        while time.monotonic() < deadline:
            line = stream.readline()
            if line:
                match = DSHOT.search(line)
                if match:
                    index = int(match.group(1))
                    if index != expected_index:
                        raise ValueError(
                            f"Missing/reordered real DShot frames: expected "
                            f"{expected_index} got {index}")
                    expected_index += 1
                    if index == LAST_DSHOT:
                        return expected_index
            else:
                if proc.poll() is not None:
                    raise RuntimeError(
                        f"QEMU exited before complete external FC source: "
                        f"frames={expected_index}, exit={proc.returncode}")
                time.sleep(0.05)
    raise TimeoutError(f"Original source DShot stopped at frame {expected_index}/3000")

def run(args):
    scenario = validate_scenario(args.scenario)
    if not args.qemu.is_file() or not args.cfg_flash.is_file() or not args.elf.is_file():
        raise FileNotFoundError("Pinned QEMU/ELF/SIM_ONLY cfg missing")
    if hashlib.sha256(args.elf.read_bytes()).hexdigest() != ELF:
        raise ValueError("Original ESCape32 Rel17.3 ELF SHA256 mismatch")
    focus = args.switch_focus_window_ms
    if focus is not None and focus != "2795:2840":
        raise ValueError("Diagnostic comparator requires exact 2795:2840 focus")
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    qemu_log = args.artifact.with_suffix(".qemu.log")
    source_log = args.artifact.with_suffix(".p0.events.log")
    command = [
        str(args.qemu.resolve()), "-machine",
        "am13e23019,esc-sim=on,esc-sim-native-motor=on,"
        "esc-sim-nfault-asserted=off,esc-sim-differential-fc-smoke=on" +
        (",esc-sim-switch-focus-window-ms=" + focus if focus else ""),
        "-kernel", str(args.elf.resolve()),
        "-display", "none", "-serial", "none", "-monitor", "none",
        "-icount", "shift=2,sleep=off,align=off",
        "-device", "loader,file=" + str(args.cfg_flash.resolve()) +
                   ",addr=0x4000,force-raw=on",
    ]
    report = {
        "schema": "e62.native.preboot-fc-source.v1",
        "status": "FAIL_PREBOOT_FC_SOURCE",
        "original_elf_sha256": ELF,
        "scenario_sha256": scenario["sha256"],
        "configured_dshot_frames": 3000,
        "source_focus_window_ms": focus,
        "source_focus_guest_or_motor_control": False,
        "host_guest_register_writes": False,
        "used_guest_wfi_or_gdb": False,
        "motor_mode": "QEMU_VIRTUAL_CLOCK_NATIVE_ECX87_KV147_SIM_ONLY",
        "differential_preboot_fc_source": True,
        "qtest_or_qmp_used": False,
        "host_virtual_time_steps": 0,
        "hardware_qualified": False,
        "motor_p1_stability_qualified": False,
    }
    try:
        with qemu_log.open("wb") as log:
            proc = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=log)
            try:
                report["passive_dshot_frames"] = passive_until_final_frame(
                    qemu_log, proc, wall_timeout_s=args.wall_timeout_s)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                log.flush()
        if qemu_log.stat().st_size > MAX_LOG_BYTES:
            raise ValueError("Full QEMU source trace exceeded 64 MiB")
        with qemu_log.open(encoding="utf-8", errors="replace") as src, (
                source_log.open("w", encoding="utf-8")) as dst:
            for line in src:
                if "E62_P0_EVENT " in line:
                    dst.write(line)
        with source_log.open(encoding="utf-8") as stream:
            events = parse_source(stream)
        original_frames = [x for x in events if x["kind"] == "DSHOT"]
        if len(original_frames) != 3000:
            raise ValueError("Complete original FC DShot source trace missing")
        if original_frames[0]["data"][0] != 0 or (
                original_frames[-1]["data"][0] != LAST_DSHOT):
            raise ValueError("Original FC DShot source sequence invalid")
        if not all(
            original_frames[i + 1]["vns"] > original_frames[i]["vns"]
            for i in range(len(original_frames) - 1)
        ):
            raise ValueError("Original QEMU virtual DShot time reversed")
        report.update(
            status="SOURCE_ONLY_PREBOOT_FC_COMPLETED_NOT_P1",
            first_dshot_vns=original_frames[0]["vns"],
            last_dshot_vns=original_frames[-1]["vns"],
            last_source_seq=events[-1]["seq"],
            source_event_count=len(events),
            source_log_sha256=hashlib.sha256(source_log.read_bytes()).hexdigest(),
            switch_focus_event_count=sum(x["kind"] == "SWITCH_FOCUS" for x in events),
        )
        return report
    except BaseException as exc:
        report["exception"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        report["qemu_log_path"] = str(qemu_log)
        report["source_log_path"] = str(source_log)
        args.artifact.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", required=True, type=Path)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--cfg-flash", required=True, type=Path)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--switch-focus-window-ms", default=None)
    parser.add_argument("--wall-timeout-s", type=int, default=210)
    args = parser.parse_args()
    if not 30 <= args.wall_timeout_s <= 600:
        parser.error("wall-timeout-s must be 30..600 seconds")
    report = run(args)
    print("E62_PREBOOT_FC_SOURCE " + json.dumps(report, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
