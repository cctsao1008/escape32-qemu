#!/usr/bin/env python3
"""G13B1 original-ELF PA26 DShot600 receive, no firmware input spoofing.

Fixture writes ONLY 0x5ffe4000 test-only external *wire edge queue*.
QEMU virtual time applies each level through its existing PA26 GPIO
capture -> TIMG4 CC0 -> DMA CH2 path. Original Rel17 ISR/decoder must
enter its OWN am13e_app_io_dshot_packet(frame, inverted) callback.
No guest RX buffer, throttle, IRQ, captured timestamp, or core register
is written by the test. Electrical board remains unqualified, no motor
or power-stage enable is permitted or implied.
"""
import argparse
import json
import subprocess
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elf_image import elf_function_address, app_vector_from_elf
from g13b_native_no_drive import symbol_address
from g12_runtime_progress import native_wfi_locations
from g11_exception_lifecycle import (
    RSP, wait_for_socket, reach_release, observer,
    add_bp, del_bp, continue_bounded
)
from g7b_pa26_capture import dshot_frame
from tools.virtual_bldc import GATE_EN, GPIO1_BASE, PINCM_BASE

WAVE = 0x5ffe4000
PA26 = 0x5ffe0000
TIMG4 = 0x40180000
DMA = 0x40020000


def write32(rsp, addr, value):
    encoded = int(value).to_bytes(4, byteorder="little").hex()
    ack = rsp.command(f"M{addr:x},4:{encoded}")
    if ack != "OK":
        raise RuntimeError(f"Simulator external input write rejected "
                           f"addr=0x{addr:08x}, ack={ack!r}")


def queue_edge(rsp, delay_ns, level):
    if not 10 <= delay_ns <= 100000000 or level not in (0, 1):
        raise ValueError("Physically invalid fixture edge")
    write32(rsp, WAVE + 0x00, delay_ns)
    write32(rsp, WAVE + 0x04, level)
    write32(rsp, WAVE + 0x18, 1)


def queue_dshot600_wire(rsp, throttle):
    if not 48 <= throttle <= 2047:
        raise ValueError("Only genuine DShot throttle data frames")
    frame = dshot_frame(throttle)
    assert rsp.mem32(WAVE + 0x08) == 0
    # DShot600 100MHz TIMG4: high bit1=125 ticks, bit0=63 ticks,
    # period=167 ticks. Each queue entry is a real pin level transition.
    queue_edge(rsp, 10000, 1)  # quiet idle before first rising edge
    for bit in range(15, -1, -1):
        high_ticks = 125 if (frame >> bit) & 1 else 63
        if bit != 15:
            queue_edge(rsp, 10 * (167 - previous_high), 1)
        queue_edge(rsp, 10 * high_ticks, 0)
        previous_high = high_ticks
    if rsp.mem32(WAVE + 0x08) != 32:
        raise AssertionError("DShot physical edge count is not 32")
    write32(rsp, WAVE + 0x1c, 1)  # launch against QEMU VIRTUAL time
    if rsp.mem32(WAVE + 0x10) != 1:
        raise AssertionError("External waveform was not scheduled")
    print(f"G13B1_REAL_INPUT_FRAME=0x{frame:04x} "
          "PA26_EDGES_SCHEDULED=32 ONLY_EXTERNAL_LINE", flush=True)
    return frame


def gate_disconnected(rsp):
    # Never infer gate polarity from unqualified Reference constants:
    # absent PB13 output enable is an independent physical disconnect.
    return ((rsp.mem32(GPIO1_BASE + 0x12c0) & GATE_EN) == 0 and
            (rsp.mem32(PINCM_BASE + 4 * 45) & 0x3f) == 1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    p.add_argument("--throttle", type=int, default=1000)
    p.add_argument("--startup-steps", type=int, default=32768)
    p.add_argument("--slice-ms", type=int, default=300)
    p.add_argument("--artifact", type=Path)
    args = p.parse_args()
    if not args.qemu.is_file() or not args.elf.is_file():
        p.error("Missing QEMU or original native ELF")
    if not 10 <= args.slice_ms <= 1500:
        p.error("Bounded slice invalid")
    app_vector_from_elf(args.elf)

    # Target must be an actual firmware function address from the ELF,
    # never a simulator-specified callback or hardcoded magic PC.
    native_callback = elf_function_address(
        args.elf, "am13e_app_io_dshot_packet")[0]
    original_wfi = native_wfi_locations(
        args.elf, "arm-none-eabi-objdump")[0]
    throt_addr = symbol_address(args.elf, "throt")
    events = []
    with tempfile.TemporaryDirectory(prefix="e62-g13b1-native-") as tmp:
        sock = str(Path(tmp) / "gdb.sock")
        cmd = [str(args.qemu.resolve()), "-M", "am13e23019,esc-sim=on",
               "-kernel", str(args.elf.resolve()), "-S",
               "-display", "none", "-serial", "none", "-monitor", "none",
               "-chardev",
               f"socket,path={sock},server=on,wait=off,id=gdb0",
               "-gdb", "chardev:gdb0",
               "-icount", "shift=2,sleep=off,align=off"]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            with wait_for_socket(sock, proc) as conn:
                rsp = RSP(conn)
                if not rsp.command("?").startswith(("S", "T")):
                    raise RuntimeError("Native QEMU not halted at reset")
                if "qXfer:features:read+" not in rsp.command(
                        "qSupported:qXfer:features:read+"):
                    raise RuntimeError("Missing QEMU core layout")
                if not rsp.command(
                        "qXfer:features:read:target.xml:0,1").startswith(
                            ("m<", "l<")):
                    raise RuntimeError("Cannot retrieve GDB target XML")
                if rsp.command("Qqemu.sstep:1") != "OK":
                    raise RuntimeError("Timed IRQ stepping unavailable")
                release, hardfault, scans = reach_release(
                    rsp, args.elf, args.startup_steps)
                armed = {original_wfi, hardfault}
                for pc in armed:
                    add_bp(rsp, pc)
                try:
                    stop, interrupted = continue_bounded(rsp, args.slice_ms)
                    if interrupted or not stop.startswith(("S05", "T05")):
                        raise AssertionError("Original main WFI not reached")
                    if rsp.reg(15) != original_wfi:
                        raise AssertionError("Fault or unexpected pre-WFI stop")
                    if rsp.mem32(throt_addr) != 0:
                        raise AssertionError("Reference throttle not neutral")
                    if not gate_disconnected(rsp):
                        raise AssertionError("Board unexpectedly gate-connected")
                    if ((rsp.mem32(PINCM_BASE + 26 * 4) &
                         0x000400bf) != 0x00040083):
                        raise AssertionError("Native TIMG4 PA26 pinmux absent")
                    if rsp.mem32(WAVE + 0x08) != 0:
                        raise AssertionError("PA26 waveform fixture not clear")
                    del_bp(rsp, original_wfi)
                    armed.remove(original_wfi)
                    frame = queue_dshot600_wire(rsp, args.throttle)
                    add_bp(rsp, native_callback)
                    armed.add(native_callback)
                    stop, interrupted = continue_bounded(rsp, args.slice_ms)
                    if interrupted or not stop.startswith(("S05", "T05")):
                        details = dict(
                            wave_queued=rsp.mem32(WAVE + 8),
                            wave_delivered=rsp.mem32(WAVE + 12),
                            wave_busy=rsp.mem32(WAVE + 16),
                            pa26_transition=rsp.mem32(PA26 + 4),
                            pa26_capture=rsp.mem32(PA26 + 8),
                            dma_beats=rsp.mem32(PA26 + 12),
                            dma_remaining=rsp.mem32(DMA + 0x122c),
                            throt=rsp.mem32(throt_addr))
                        print("G13B1_NATIVE_CALLBACK_TIMEOUT "
                              + json.dumps(details), flush=True)
                        raise AssertionError(
                            "No native DShot callback observed in bounded run")
                    pc = rsp.reg(15)
                    if pc == hardfault:
                        raise AssertionError("Native HardFault after DShot waveform")
                    if pc != native_callback:
                        raise AssertionError(f"Unexpected stop 0x{pc:08x}")
                    guest_frame = rsp.reg(0) & 0xffff
                    inverted = rsp.reg(1) & 0xffffffff
                    capture = rsp.mem32(PA26 + 8)
                    dma_beats = rsp.mem32(PA26 + 12)
                    remaining = rsp.mem32(DMA + 0x122c)
                    delivered = rsp.mem32(WAVE + 12)
                    gate_off = gate_disconnected(rsp)
                    record = dict(frame=frame, guest_frame=guest_frame,
                                  inverted=inverted, delivered=delivered,
                                  capture=capture, dma_beats=dma_beats,
                                  dma_remaining=remaining,
                                  gate_disconnected=gate_off,
                                  pc=pc, throttle_pre_callback=
                                  rsp.mem32(throt_addr))
                    events.append(record)
                    print("G13B1_NATIVE_RECEIVE_CALLBACK " +
                          json.dumps(record, sort_keys=True), flush=True)
                    if (guest_frame != frame or delivered != 32 or
                            capture < 32 or dma_beats < 32 or not gate_off or
                            observer(rsp)["ipsr"] != 0):
                        raise AssertionError(
                            "Native DShot frame/capture/DMA/drive ownership mismatch")
                    print("PASS_G13B1_ORIGINAL_ELF_DSHOT_RX_FROM_PA26_WIRE "
                          "NOT_NATIVE_ARMING_OR_CLOSED_LOOP", flush=True)
                finally:
                    for pc in sorted(armed, reverse=True):
                        del_bp(rsp, pc)
        finally:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            if proc.stderr:
                if proc.returncode not in (0, -15):
                    stderr = proc.stderr.read()
                    if stderr:
                        print("G13B1_QEMU_STDERR " + stderr[-2500:])
                proc.stderr.close()
    if args.artifact:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(events, indent=2) + "\n")


if __name__ == "__main__":
    main()
