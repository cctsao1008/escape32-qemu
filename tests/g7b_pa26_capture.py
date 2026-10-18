#!/usr/bin/env python3
"""G7b: PA26 external signal level -> TIMG4 CC0 -> DMA0 CH2 -> guest SRAM.

This validates real timestamp transport, not a decoded firmware packet.
All edges are individually driven through an ESC-SIM ONLY input port.
"""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

STIMULUS = 0x5FFE0000
GPIO = 0x400F0000
PINCM_PA26 = 0x400CC000 + 26 * 4
TIMER = 0x40180000
DMA = 0x40020000
SRC, DST, SIZE, CTL = (DMA + 0x1224, DMA + 0x1228,
                       DMA + 0x122C, DMA + 0x1220)
TRIG = DMA + 0x1118
BUFFER = 0x20000A00
CC0 = TIMER + 0x1810
DMAMASK, DMARIS, DMACLEAR = DMA + 0x1028, DMA + 0x1030, DMA + 0x1048
DMACH2_RX_CTL = 0x00302272  # word-word; fixed src; dst +1; half IRQ

def dshot_frame(throttle, telemetry=0):
    data = (throttle << 1) | telemetry
    crc = (data ^ (data >> 4) ^ (data >> 8)) & 0xF
    return (data << 4) | crc

def run(qemu, elf, sim, inspect):
    with tempfile.TemporaryDirectory(prefix="am13e-pa26-") as tmp:
        sockpath = os.path.join(tmp, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(sockpath)
            server.listen(1)
            server.settimeout(15)
            proc = subprocess.Popen([
                str(qemu), "-machine",
                "am13e23019,accel=qtest,esc-sim=" +
                ("on" if sim else "off"),
                "-kernel", str(elf), "-display", "none", "-serial", "none",
                "-monitor", "none", "-qtest", f"unix:path={sockpath}"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                connection, _ = server.accept()
                with connection:
                    inspect(QTest(connection))
            finally:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                err = proc.stderr.read()
                proc.stderr.close()
    return err

def init(q):
    q.write(GPIO + 0x0800, 0x26000001)
    q.write(TIMER + 0x0800, 0x26000001)
    q.write(TIMER + 0x1008, 8)  # BUSCLK / 1
    q.write(TIMER + 0x1000, 0)
    q.write(TIMER + 0x110C, 0)
    q.write(TIMER + 0x1108, 1)  # timer clock enabled
    q.write(TIMER + 0x1808, 0xFFFF)
    q.write(TIMER + 0x1830, 0x00020003)  # Capture + both edges
    q.write(TIMER + 0x1804, 0x20000023)  # 100MHz up+repeat
    q.write(DMAMASK, (1 << 2) | (1 << 18) | (1 << 24))
    q.write(SRC, CC0)
    q.write(DST, BUFFER)
    q.write(SIZE, 32)
    q.write(TRIG, 34)  # external TIMG4_0_GEN_EVENT1
    q.write(CTL, DMACH2_RX_CTL)
    for i in range(32):
        q.write(BUFFER + 4*i, 0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", type=Path, required=True)
    ap.add_argument("--elf", type=Path, required=True)
    args = ap.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for p in (qemu, elf):
        if not p.is_file():
            ap.error(f"File not found: {p}")

    def functional(q):
        assert q.read(STIMULUS) == 0
        assert q.read(STIMULUS + 4) == 0
        assert q.read(STIMULUS + 8) == 0
        assert q.read(STIMULUS + 12) == 0
        init(q)

        # A bare pin transition cannot create capture or DMA data.
        q.write(STIMULUS, 1)
        q.write(STIMULUS, 0)
        assert q.read(STIMULUS + 4) == 2
        assert q.read(STIMULUS + 8) == 0
        assert q.read(STIMULUS + 12) == 0
        assert q.read(SIZE) == 32
        print("G7B_UNROUTED_PA26_NO_CAPTURE_NO_DMA=PASS")

        # PA26 TIMG4 CCP0 mux (PF3), PC and INENA are required.
        q.write(PINCM_PA26, 0x00040083)
        # Without a CCU0-up event mask, capture occurs but DMA
        # remains idle; verify no invented request.
        q.cmd("clock_step 100")
        q.write(STIMULUS, 1)
        assert q.read(STIMULUS + 8) == 1
        assert q.read(SIZE) == 32
        assert q.read(GPIO + 0x1380) & (1 << 26)
        q.write(STIMULUS, 0)
        assert not q.read(GPIO + 0x1380) & (1 << 26)
        assert q.read(STIMULUS + 8) == 2
        assert q.read(STIMULUS + 12) == 0
        print("G7B_CAPTURE_NO_EVENT_MASK_NO_DMA=PASS")

        # Enable GEN_EVENT1.CCU0 but reject wrong DMA trigger.
        q.write(TIMER + 0x1088, 1 << 8)
        q.write(TRIG, 35)
        q.write(STIMULUS, 1)
        q.write(STIMULUS, 0)
        assert q.read(SIZE) == 32
        assert q.read(STIMULUS + 12) == 0
        print("G7B_WRONG_DMA_TRIGGER_NO_TRANSFER=PASS")

        # Clear previous event status and restore correct DMA source.
        q.write(TIMER + 0x10A8, 1 << 8)
        q.write(TRIG, 34)
        cap_before = q.read(STIMULUS + 8)
        beat_before = q.read(STIMULUS + 12)
        q.write(DMACLEAR, 0xFFFFFFFF)

        frame = dshot_frame(1000)
        expected = []
        ticks = 0
        # DShot600: 100 MHz tick=10ns, nominal bit period 1.67us;
        # high widths 0->0.63us, 1->1.25us.
        for bit in range(15, -1, -1):
            high = 125 if (frame >> bit) & 1 else 63
            q.cmd("clock_step 200" if bit == 15 else "clock_step 0")
            if bit == 15:
                ticks += 20
            q.write(STIMULUS, 1)
            expected.append(ticks)
            q.cmd(f"clock_step {high * 10}")
            ticks += high
            q.write(STIMULUS, 0)
            expected.append(ticks)
            q.cmd(f"clock_step {(167 - high) * 10}")
            ticks += (167 - high)

        assert q.read(STIMULUS + 8) - cap_before == 32
        assert q.read(STIMULUS + 12) - beat_before == 32
        assert q.read(SIZE) == 0
        assert (q.read(CTL) & 2) == 0
        assert q.read(DMARIS) & (1 << 2)
        assert q.read(DMARIS) & (1 << 18)
        stamps = [q.read(BUFFER + i*4) for i in range(32)]
        assert all(a < b for a, b in zip(stamps, stamps[1:])), stamps
        assert q.read(CC0) == stamps[-1]
        # First-edge timestamp has a preamble from the gating checks.
        # Differential widths must reproduce every originally sent bit.
        decoded = 0
        for i in range(16):
            width = stamps[2*i + 1] - stamps[2*i]
            assert width in (63, 125), (i, width, stamps)
            decoded = (decoded << 1) | int(width >= 94)
        assert decoded == frame, (hex(decoded), hex(frame))
        assert (decoded & 0xF) == ((decoded >> 4) ^
                   (decoded >> 8) ^ (decoded >> 12)) & 0xF
        print(f"G7B_32_EDGES_DMA_SRAM_DSHOT600=0x{decoded:04X} PASS")
        print("G7B_TIMG4_CAPTURE_TIMESTAMP_AND_CH2_IRQ=PASS")

        # Without a new DMA arm, further pin transitions only update
        # TIMG4 CC0; the completed buffer remains stable.
        q.write(STIMULUS, 1)
        q.write(STIMULUS, 0)
        assert q.read(STIMULUS + 12) - beat_before == 32
        assert [q.read(BUFFER + i*4) for i in range(32)] == stamps
        print("PASS_G7B_PA26_EDGE_TO_CAPTURE_TO_REAL_DMA_NO_PHANTOM")

    run(qemu, elf, True, functional)

    def strict(q):
        q.write(STIMULUS, 1)
        q.read(STIMULUS)

    err = run(qemu, elf, False, strict)
    assert "G7B_INVALID_PA26_INJECTION" in err, err
    print("PASS_G7B_STRICT_MODE_REJECTS_SIM_INPUT")

if __name__ == "__main__":
    main()
