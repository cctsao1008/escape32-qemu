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
import socket
import subprocess
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elf_image import elf_function_address, app_vector_from_elf
from g13b_native_no_drive import symbol_address
from g12_runtime_progress import native_wfi_locations
from g13b_native_wfi import wait_for_native_main_wfi
from g11_exception_lifecycle import (
    RSP, wait_for_socket, reach_release, observer,
    add_bp, del_bp, continue_bounded
)
from g7b_pa26_capture import dshot_frame
from g0_memory import QTest
from tools.virtual_bldc import GATE_EN, GPIO1_BASE, PINCM_BASE

WAVE = 0x5ffe4000
PA26 = 0x5ffe0000
TIMG4 = 0x40180000
DMA = 0x40020000


def queue_edge(qtest, delay_ns, level):
    if not 10 <= delay_ns <= 100000000 or level not in (0, 1):
        raise ValueError("Physically invalid fixture edge")
    # QEMU 6.2 GDB RSP M packets use address_space_write_rom and
    # IGNORE MMIO writes while falsely returning OK. An independent
    # out-of-band QTest socket with native TCG is required to perform
    # REAL address_space_write() against the simulator-only input port.
    before = qtest.read(WAVE + 0x08)
    qtest.write(WAVE + 0x00, delay_ns)
    qtest.write(WAVE + 0x04, level)
    qtest.write(WAVE + 0x18, 1)
    after = qtest.read(WAVE + 0x08)
    if after != before + 1:
        raise AssertionError(f"External edge not committed "
                             f"before={before}, after={after}, level={level}")


def encode_dshot_physical_frame(throttle, *, corrupt_crc=False):
    """Physical wire frame; corruption changes only checksum bit zero."""
    frame = dshot_frame(throttle)
    return frame ^ (1 if corrupt_crc else 0)


def queue_dshot600_wire(qtest, throttle, *, allow_zero=False,
                         reset_completed_wave=False, corrupt_crc=False):
    if not (48 <= throttle <= 2047 or (throttle == 0 and allow_zero)):
        raise ValueError("Only genuine DShot throttle or opt-in zero frames")
    if reset_completed_wave:
        # Reset ONLY the simulator's external PA26 waveform queue, and
        # only once its previous physical edges fully reached PA26.
        # Never touch Guest's timer, DMA, ISR, SRAM, or decoded throttle.
        if (qtest.read(WAVE + 0x10) != 0 or
                qtest.read(WAVE + 0x08) != 32 or
                qtest.read(WAVE + 0x0c) != 32):
            raise AssertionError("Cannot reset active/undelivered PA26 wire")
        qtest.write(WAVE + 0x20, 1)
        if qtest.read(WAVE + 0x08) != 0 or qtest.read(WAVE + 0x0c) != 0:
            raise AssertionError("SIM_ONLY PA26 wire queue did not reset")
    # Deliberately corrupt ONLY the transmitted physical wire checksum.
    # Original Guest must execute its unmodified decoder and reject.
    frame = encode_dshot_physical_frame(throttle, corrupt_crc=corrupt_crc)
    assert qtest.read(WAVE + 0x08) == 0
    # DShot600 100MHz TIMG4: high bit1=125 ticks, bit0=63 ticks,
    # period=167 ticks. Each queue entry is a real pin level transition.
    queue_edge(qtest, 10000, 1)  # quiet idle before first rising edge
    for bit in range(15, -1, -1):
        high_ticks = 125 if (frame >> bit) & 1 else 63
        if bit != 15:
            queue_edge(qtest, 10 * (167 - previous_high), 1)
        queue_edge(qtest, 10 * high_ticks, 0)
        previous_high = high_ticks
    if qtest.read(WAVE + 0x08) != 32:
        raise AssertionError("DShot physical edge count is not 32")
    qtest.write(WAVE + 0x1c, 1)  # QEMU virtual-time arm, not guest write
    if qtest.read(WAVE + 0x10) != 1:
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
    p.add_argument("--corrupt-crc", action="store_true",
                   help="Transmit one genuinely malformed DShot wire frame; require original Guest CRC rejection")
    p.add_argument("--startup-steps", type=int, default=32768)
    p.add_argument("--slice-ms", type=int, default=300)
    p.add_argument("--runtime-slices", type=int, default=12)
    p.add_argument("--artifact", type=Path)
    args = p.parse_args()
    if not args.qemu.is_file() or not args.elf.is_file():
        p.error("Missing QEMU or original native ELF")
    if not 10 <= args.slice_ms <= 1500 or not 1 <= args.runtime_slices <= 30:
        p.error("Bounded slice or runtime-slices invalid")
    app_vector_from_elf(args.elf)

    # Target must be an actual firmware function address from the ELF,
    # never a simulator-specified callback or hardcoded magic PC.
    native_callback = elf_function_address(
        args.elf, "am13e_app_io_dshot_packet")[0]
    native_wfi_pcs = native_wfi_locations(
        args.elf, "arm-none-eabi-objdump")
    throt_addr = symbol_address(args.elf, "throt")
    events = []
    with tempfile.TemporaryDirectory(prefix="e62-g13b1-native-") as tmp:
        sock = str(Path(tmp) / "gdb.sock")
        qtpath = str(Path(tmp) / "qtest.sock")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(qtpath)
        listener.listen(1)
        listener.settimeout(15)
        cmd = [str(args.qemu.resolve()), "-M", "am13e23019,esc-sim=on",
               "-kernel", str(args.elf.resolve()), "-S",
               "-display", "none", "-serial", "none", "-monitor", "none",
               "-chardev",
               f"socket,path={sock},server=on,wait=off,id=gdb0",
               "-gdb", "chardev:gdb0",
               "-qtest", f"unix:path={qtpath}",
               "-icount", "shift=2,sleep=off,align=off"]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        qsock = None
        try:
            qsock, _ = listener.accept()
            qtest = QTest(qsock)
            print("G13B1_TCG_QTEST_EXTERNAL_PORT_CONNECTED "
                  "NO_GUEST_REGISTER_WRITES", flush=True)
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
                armed = {*native_wfi_pcs, hardfault}
                for pc in sorted(armed):
                    add_bp(rsp, pc)
                try:
                    observed_wfi = wait_for_native_main_wfi(
                        rsp, native_wfi_pcs, hardfault, args.slice_ms,
                        args.runtime_slices, stage="B1_PRE_COMMAND_WFI")
                    # Native src/main.c deliberately seeds
                    # throt=1 during its 250ms arming window; this
                    # is not a decoded motor throttle or a safety bypass.
                    pre_command_throt = rsp.mem32(throt_addr)
                    if pre_command_throt not in (0, 1):
                        raise AssertionError(
                            "Unexpected non-neutral native throttle before "
                            f"external DShot: {pre_command_throt}")
                    if not gate_disconnected(rsp):
                        raise AssertionError("Board unexpectedly gate-connected")
                    if ((rsp.mem32(PINCM_BASE + 26 * 4) &
                         0x000400bf) != 0x00040083):
                        raise AssertionError("Native TIMG4 PA26 pinmux absent")
                    if rsp.mem32(WAVE + 0x08) != 0:
                        raise AssertionError("PA26 waveform fixture not clear")
                    # All WFI breakpoints must be removed before
                    # command ingress: firmware may follow either
                    # real WFI branch while decoding the external wire.
                    for native_wfi in native_wfi_pcs:
                        del_bp(rsp, native_wfi)
                        armed.remove(native_wfi)
                    print(f"G13B1_PRE_COMMAND_NATIVE_WFI=0x{observed_wfi:08x}",
                          flush=True)
                    frame = queue_dshot600_wire(qtest, args.throttle,
                                                 corrupt_crc=args.corrupt_crc)
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
                                  ipsr=observer(rsp)["ipsr"], pc=pc,
                                  throttle_pre_callback=rsp.mem32(throt_addr))
                    events.append(record)
                    print("G13B1_NATIVE_RECEIVE_CALLBACK " +
                          json.dumps(record, sort_keys=True), flush=True)
                    if (guest_frame != frame or delivered != 32 or
                            capture < 32 or dma_beats < 32 or not gate_off or
                            record["ipsr"] == 3):
                        raise AssertionError(
                            "Native DShot frame/capture/DMA/drive ownership mismatch")
                    print("G13B1_FRAME_REACHED_ORIGINAL_ELF_CALLBACK=PASS",
                          flush=True)

                    # A breakpoint at the callback entry alone does NOT
                    # demonstrate CRC acceptance or throttle policy. Run the
                    # *unaltered* guest callback all the way to its original
                    # caller's return PC and inspect its original return
                    # value and actual Rel17 throttle variable afterward.
                    return_pc = rsp.reg(14) & ~1
                    if not 0x6000 <= return_pc < 0x80000 or return_pc == pc:
                        raise AssertionError(
                            f"Non-native callback return PC 0x{return_pc:08x}")
                    del_bp(rsp, native_callback)
                    armed.remove(native_callback)
                    add_bp(rsp, return_pc)
                    armed.add(return_pc)
                    stop, interrupted = continue_bounded(rsp, args.slice_ms)
                    if interrupted or not stop.startswith(("S05", "T05")):
                        raise AssertionError("Native DShot callback never returned")
                    if rsp.reg(15) == hardfault:
                        raise AssertionError("HardFault during native CRC/policy")
                    if rsp.reg(15) != return_pc:
                        raise AssertionError(
                            f"Unexpected native callback return PC 0x{rsp.reg(15):08x}")
                    crc_accepted = rsp.reg(0) & 0xffffffff
                    throttle_after = rsp.mem32(throt_addr)
                    gate_still_off = gate_disconnected(rsp)
                    record.update(callback_return_pc=return_pc,
                                  callback_return=crc_accepted,
                                  throttle_after_callback=throttle_after,
                                  gate_disconnected_after_callback=
                                  gate_still_off)
                    print("G13B1_NATIVE_CRC_THROTTLE_POLICY " +
                          json.dumps({"return_value": crc_accepted,
                                      "throttle_before":
                                      record["throttle_pre_callback"],
                                      "throttle_after": throttle_after,
                                      "gate_still_isolated": gate_still_off}),
                          flush=True)
                    if args.corrupt_crc:
                        # Reject the malformed CRC in the original callback,
                        # without inventing a Guest RX frame or writing SRAM.
                        if (crc_accepted != 0 or
                                throttle_after != record["throttle_pre_callback"] or
                                not gate_still_off or observer(rsp)["cfsr"]):
                            raise AssertionError(
                                "Original Guest did not reject physical bad CRC fail-closed")
                        print("PASS_E62_ORIGINAL_ELF_BAD_DSHOT_CRC_REJECTED "
                              "GATE_STILL_ISOLATED", flush=True)
                    else:
                        if (crc_accepted != 1 or throttle_after <= 1 or
                                throttle_after == record["throttle_pre_callback"] or
                                not gate_still_off or observer(rsp)["cfsr"]):
                            raise AssertionError(
                                "Native DShot CRC/throttle ownership not demonstrated")
                        print("PASS_G13B1_ORIGINAL_ELF_DSHOT_RX_CRC_THROTTLE "
                              "GATE_STILL_ISOLATED_NOT_CLOSED_LOOP", flush=True)
                finally:
                    for pc in sorted(armed, reverse=True):
                        del_bp(rsp, pc)
        finally:
            if qsock is not None:
                qsock.close()
            listener.close()
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
