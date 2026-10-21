#!/usr/bin/env python3
"""G13B2E EXPERIMENT: native SIM_ONLY DShot -> motor start -> gate evidence.

Never forge guest throttle/PWM/Gate/Trip/IRQ. QTest owns physical PA26
wire edges and three healthy external current samples ONLY. Firmware must
process the DShot CRC, execute motor_output_start(), survive trip preflight,
then call power_stage_enable() after real PWM zero events.

By default this is a bounded *diagnostic*, never a claimed PASS if native
actuation is not observed. --require-drive makes these conditions a strict
acceptance gate. Not a sensorless closed-loop or real-board safety claim.
"""
import argparse
import json
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elf_image import app_vector_from_elf, elf_function_address
from g0_memory import QTest
from g1_handoff import RSP, wait_for_socket
from g11_exception_lifecycle import (
    reach_release, observer, add_bp, del_bp, continue_bounded
)
from g12_runtime_progress import native_wfi_locations
from g13b_native_wfi import wait_for_native_main_wfi
from g13b_native_no_drive import symbol_address
from g13b_native_dshot import queue_dshot600_wire, WAVE, PA26
from g13b2_native_safety import snapshot, verify, EXT_OC, PWM4
from tools.virtual_bldc import gate_and_pads_connected

FAULT_FN = "am13e_app_motor_fault_reset"


def resume_to(rsp, target, hardfault, slice_ms, slices, label):
    for n in range(slices):
        stop, interrupted = continue_bounded(rsp, slice_ms)
        if not stop.startswith(("S02", "T02", "S05", "T05")):
            raise RuntimeError(f"{label} unexpected GDB stop {stop!r}")
        state = observer(rsp)
        if (state["pc"] == hardfault or state["cfsr"] or state["hfsr"]):
            raise AssertionError(f"{label} original firmware CPU fault: {state}")
        if not interrupted:
            if state["pc"] != target:
                raise AssertionError(
                    f"{label}: unexpected breakpoint 0x{state['pc']:08x}")
            return
    raise AssertionError(f"{label} native guest did not reach "
                         f"0x{target:08x} in {slices} bounded slices")


def trace_original_start_preconditions(rsp, symbols, armed,
                                       hardfault, slice_ms, max_slices):
    """Inspect actual native readiness return values; no guest mutations.

    Do not assume which guard rejected motor startup. Watch calls to
    the two separate original-ELF readiness functions, their real
    caller-return PCs and final motor_output_start return register.
    """
    original_return = rsp.reg(14) & ~1
    if not 0x6000 <= original_return < 0x80000:
        raise AssertionError("Original motor start LR outside app text")
    watched = ("am13e_app_motor_nfault_trip_ready",
               "am13e_app_motor_bemf_reference_start_ready")
    entrances = {symbols[name]: name for name in watched}
    pending = {}
    result = {}
    add_bp(rsp, original_return)
    armed.add(original_return)
    for addr in sorted(entrances):
        add_bp(rsp, addr)
        armed.add(addr)
    try:
        for i in range(max_slices * 8):
            stop, paused = continue_bounded(rsp, slice_ms)
            if not stop.startswith(("S02", "T02", "S05", "T05")):
                raise RuntimeError(f"Native start trace stop={stop!r}")
            cpu = observer(rsp)
            pc = cpu["pc"]
            if pc == hardfault or cpu["cfsr"] or cpu["hfsr"]:
                raise AssertionError(f"CPU fault during native start {cpu}")
            if paused:
                continue
            if pc == original_return:
                result["native_start_return"] = rsp.reg(0)
                print("G13B2E_NATIVE_START_FUNCTION_RETURNS " +
                      json.dumps(result, sort_keys=True), flush=True)
                return result
            if pc == symbols[FAULT_FN]:
                result["status"] = "FAULT_RESET_INSIDE_START"
                return result
            if pc in entrances:
                name = entrances[pc]
                lr = rsp.reg(14) & ~1
                if not 0x6000 <= lr < 0x80000 or lr in pending or lr == original_return:
                    raise AssertionError(f"Invalid native readiness return: {name}, {lr:x}")
                del_bp(rsp, pc)
                armed.remove(pc)
                add_bp(rsp, lr)
                armed.add(lr)
                pending[lr] = name
                result[name + "_called"] = 1
                continue
            if pc in pending:
                name = pending.pop(pc)
                result[name + "_return"] = rsp.reg(0)
                print(f"G13B2E_NATIVE_PRECONDITION {name} "
                      f"return_value={rsp.reg(0)}", flush=True)
                del_bp(rsp, pc)
                armed.remove(pc)
                continue
            raise AssertionError(f"Native start trace unexpected PC={pc:08x}")
        result["status"] = "START_TRACE_TIMEOUT"
        return result
    finally:
        for addr in (original_return, *entrances.keys(), *pending.keys()):
            if addr in armed:
                del_bp(rsp, addr)
                armed.remove(addr)


def run(args):
    app_vector_from_elf(args.elf)
    wfi = native_wfi_locations(args.elf, args.objdump)
    throt = symbol_address(args.elf, "throt")
    symbols = {
        name: elf_function_address(args.elf, name)[0]
        for name in ("am13e_app_io_dshot_packet", "am13e_motor_output_start",
                     "am13e_power_stage_enable", FAULT_FN,
                     "am13e_app_motor_nfault_trip_ready",
                     "am13e_app_motor_bemf_reference_start_ready")
    }
    evidence = {"status": "OPEN_NOT_NATIVE_DRIVE", "native_elf": str(args.elf)}
    with tempfile.TemporaryDirectory(prefix="g13b2e-probe-") as tmp:
        qtpath = str(Path(tmp) / "qtest.sock")
        gdbpath = str(Path(tmp) / "gdb.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(qtpath)
            listener.listen(1)
            listener.settimeout(15)
            proc = subprocess.Popen([
                str(args.qemu.resolve()), "-M",
                "am13e23019,esc-sim=on,esc-sim-nfault-asserted=off",
                "-kernel", str(args.elf.resolve()), "-S",
                "-display", "none", "-serial", "none", "-monitor", "none",
                "-chardev", f"socket,path={gdbpath},server=on,wait=off,id=gdb0",
                "-gdb", "chardev:gdb0", "-qtest", f"unix:path={qtpath}",
                "-icount", "shift=2,sleep=off,align=off"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            qtconn = None
            armed = set()
            try:
                qtconn, _ = listener.accept()
                qtest = QTest(qtconn)
                for phase in range(3):
                    qtest.write(EXT_OC + 4*phase, 0x10000 | 1000)
                with wait_for_socket(gdbpath, proc) as conn:
                    rsp = RSP(conn)
                    if not rsp.command("?").startswith(("S", "T")):
                        raise RuntimeError("Native original CPU not stopped")
                    if "qXfer:features:read+" not in rsp.command(
                            "qSupported:qXfer:features:read+"):
                        raise RuntimeError("GDB target XML unavailable")
                    if not rsp.command(
                            "qXfer:features:read:target.xml:0,1").startswith(("m<", "l<")):
                        raise RuntimeError("Missing CPU XML")
                    if rsp.command("Qqemu.sstep:1") != "OK":
                        raise RuntimeError("Native virtual-time stepping not enabled")
                    _, hardfault, _ = reach_release(
                        rsp, args.elf, args.startup_steps)
                    armed = {*wfi, hardfault}
                    for pc in sorted(armed):
                        add_bp(rsp, pc)
                    try:
                        rendezvous = wait_for_native_main_wfi(
                            rsp, wfi, hardfault, args.slice_ms,
                            args.runtime_slices, stage="B2E_NEUTRAL")
                        neutral = snapshot(rsp, throt)
                        verify(neutral)
                        evidence["neutral_wfi"] = rendezvous
                        for pc in wfi:
                            del_bp(rsp, pc)
                            armed.remove(pc)
                        # Native, non-synthetic DShot600 command.
                        frame = queue_dshot600_wire(qtest, args.throttle)
                        callback = symbols["am13e_app_io_dshot_packet"]
                        add_bp(rsp, callback)
                        armed.add(callback)
                        resume_to(rsp, callback, hardfault, args.slice_ms,
                                  args.runtime_slices, "NATIVE_DSHOT_CALLBACK")
                        guest_frame = rsp.reg(0) & 0xffff
                        delivered = rsp.mem32(WAVE + 0x0c)
                        capture = rsp.mem32(PA26 + 0x08)
                        dma = rsp.mem32(PA26 + 0x0c)
                        evidence.update(frame=frame, guest_frame=guest_frame,
                                        wave_delivered=delivered,
                                        tim_capture=capture, dma_beats=dma)
                        if (frame != guest_frame or delivered != 32 or
                                capture != 32 or dma != 32):
                            raise AssertionError(
                                "SIM_ONLY command not from genuine PA26+DMA")
                        ret = rsp.reg(14) & ~1
                        if not 0x6000 <= ret < 0x80000:
                            raise AssertionError("Unexpected native DShot LR")
                        del_bp(rsp, callback)
                        armed.remove(callback)
                        add_bp(rsp, ret)
                        armed.add(ret)
                        resume_to(rsp, ret, hardfault, args.slice_ms,
                                  args.runtime_slices, "NATIVE_DSHOT_CRC")
                        crc_ok = rsp.reg(0)
                        native_throt = rsp.mem32(throt)
                        evidence.update(callback_return=crc_ok,
                                        native_throttle=native_throt)
                        if crc_ok != 1 or native_throt <= 1:
                            raise AssertionError(
                                "Original SIM_ONLY firmware did not accept "
                                "DShot command and update its own throttle")
                        print("G13B2E_ORIGINAL_DSHOT_CRC_ACCEPTED " +
                              json.dumps(evidence, sort_keys=True), flush=True)
                        del_bp(rsp, ret)
                        armed.remove(ret)

                        # No host-authored motor start. Discover first
                        # native motor-output start or fault-reset outcome.
                        for name in ("am13e_motor_output_start",
                                     "am13e_power_stage_enable", FAULT_FN):
                            add_bp(rsp, symbols[name])
                            armed.add(symbols[name])
                        saw_output_start = False
                        saw_gate_call = False
                        for n in range(args.runtime_slices):
                            stop, interrupted = continue_bounded(rsp, args.slice_ms)
                            if not stop.startswith(("S02", "T02", "S05", "T05")):
                                raise RuntimeError(f"G13B2E unexpected stop {stop!r}")
                            state = observer(rsp)
                            current = snapshot(rsp, throt)
                            if state["pc"] == hardfault or state["cfsr"] or state["hfsr"]:
                                evidence.update(status="NATIVE_CPU_FAULT",
                                                cpu=state, runtime=current)
                                raise AssertionError(
                                    "Native SIM_ONLY CPU fault during positive input")
                            if interrupted:
                                if n == args.runtime_slices - 1:
                                    evidence.update(status="NO_NATIVE_START_WITHIN_BOUNDS",
                                                    cpu=state, runtime=current)
                                continue
                            if state["pc"] == symbols[FAULT_FN]:
                                evidence.update(status="NATIVE_SAFETY_FAULT_RESET",
                                                cpu=state, runtime=current)
                                break
                            if state["pc"] == symbols["am13e_motor_output_start"]:
                                saw_output_start = True
                                evidence["start_entry"] = current
                                print("G13B2E_NATIVE_MOTOR_OUTPUT_START_CALLED "
                                      "GUEST_ORIGINAL_FIRMWARE", flush=True)
                                del_bp(rsp, state["pc"])
                                armed.remove(state["pc"])
                                preconditions = trace_original_start_preconditions(
                                    rsp, symbols, armed, hardfault,
                                    args.slice_ms, args.runtime_slices)
                                evidence["native_start_preconditions"] = preconditions
                                if preconditions.get("status"):
                                    evidence["status"] = preconditions["status"]
                                    break
                                if preconditions.get("native_start_return") != 1:
                                    evidence["status"] = "NATIVE_MOTOR_START_REJECTED"
                                    break
                                continue
                            if state["pc"] == symbols["am13e_power_stage_enable"]:
                                saw_gate_call = True
                                evidence["gate_enable_entry"] = current
                                if not saw_output_start:
                                    raise AssertionError(
                                        "Gate enable reached without native "
                                        "motor output start")
                                print("G13B2E_NATIVE_GATE_ENABLE_CALLED "
                                      "GUEST_ORIGINAL_FIRMWARE", flush=True)
                                ret_gate = rsp.reg(14) & ~1
                                if not 0x6000 <= ret_gate < 0x80000:
                                    raise AssertionError(
                                        "Gate enable LR invalid")
                                del_bp(rsp, state["pc"])
                                armed.remove(state["pc"])
                                add_bp(rsp, ret_gate)
                                armed.add(ret_gate)
                                resume_to(rsp, ret_gate, hardfault, args.slice_ms,
                                          args.runtime_slices, "NATIVE_GATE_RETURN")
                                after = snapshot(rsp, throt)
                                connected = gate_and_pads_connected(
                                    rsp.mem32, gate_active_level=1)
                                evidence.update(gate_return=rsp.reg(0),
                                                gate_connected=connected,
                                                gate_post=after,
                                                status="NATIVE_GATE_ON" if connected
                                                and after["pwm_running"] and
                                                after["perclkcr"] & 1 and
                                                not after["tzflags"] else
                                                "NATIVE_GATE_NOT_FULLY_AUTHORIZED")
                                break
                            raise AssertionError(
                                f"Unexpected native breakpoint PC=0x{state['pc']:08x}")
                        evidence["saw_output_start"] = saw_output_start
                        evidence["saw_gate_call"] = saw_gate_call
                        print("G13B2E_DIAGNOSTIC " +
                              json.dumps(evidence, sort_keys=True), flush=True)
                        if evidence["status"] == "NATIVE_GATE_ON":
                            print("PASS_G13B2E_ORIGINAL_SIM_ONLY_GATE_PWM_AUTHORIZATION "
                                  "NOT_SENSORLESS_CLOSED_LOOP", flush=True)
                        elif args.require_drive:
                            raise AssertionError(
                                "Native original-ELF Gate/PWM not authorized: "
                                + evidence["status"])
                        else:
                            print("G13B2E_OPEN_NO_POSITIVE_NATIVE_DRIVE_PROOF",
                                  flush=True)
                    finally:
                        for pc in sorted(armed, reverse=True):
                            del_bp(rsp, pc)
            finally:
                if qtconn is not None:
                    qtconn.close()
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                if proc.stderr:
                    if proc.returncode not in (0, -15):
                        print("G13B2E_QEMU_STDERR " +
                              proc.stderr.read()[-3000:])
                    proc.stderr.close()
    if args.artifact:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(evidence, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    p.add_argument("--throttle", type=int, default=1000)
    p.add_argument("--objdump", default="arm-none-eabi-objdump")
    p.add_argument("--startup-steps", type=int, default=32768)
    p.add_argument("--slice-ms", type=int, default=300)
    p.add_argument("--runtime-slices", type=int, default=20)
    p.add_argument("--require-drive", action="store_true")
    p.add_argument("--artifact", type=Path)
    a = p.parse_args()
    if not a.qemu.is_file() or not a.elf.is_file():
        p.error("Missing QEMU or genuine SIM_ONLY ELF")
    run(a)


if __name__ == "__main__":
    main()
