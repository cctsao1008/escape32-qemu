#!/usr/bin/env python3
"""G13B1: schedule *physical* PA26 DShot600 line edges in virtual time.

QTest owns only an independent external wire waveform and initial timer/
DMA fixture. A real TIMG4 capture event + native DMA CH2 transfer must
produce actual 32 edge timestamps. The waveform scheduler NEVER decodes
DShot, calls a guest callback, writes RX SRAM or generates IRQs directly.
"""
import argparse
from pathlib import Path

from g7b_pa26_capture import (
    run, init, dshot_frame, GPIO, TIMER, DMA, STIMULUS,
    PINCM_PA26, TRIG, SIZE, BUFFER, CC0
)

WAVE = 0x5FFE4000
NUM = WAVE + 0x08
DONE = WAVE + 0x0c
BUSY = WAVE + 0x10
LINE = WAVE + 0x14
PUSH = WAVE + 0x18
START = WAVE + 0x1c
CLEAR = WAVE + 0x20


def add_edge(q, ns, level):
    assert 10 <= ns <= 100000000
    assert level in (0, 1)
    q.write(WAVE + 0x00, ns)
    q.write(WAVE + 0x04, level)
    q.write(PUSH, 1)


def test_wave(q):
    assert q.read(NUM) == q.read(DONE) == q.read(BUSY) == 0
    assert q.read(LINE) == 0

    # Without guest pinmux/TIMG4 capture, a physical pulse must never
    # manufacture the DMA buffer, even if it is a valid PA26 transition.
    add_edge(q, 100, 1)
    add_edge(q, 100, 0)
    assert q.read(NUM) == 2
    q.write(START, 1)
    q.cmd("clock_step 250")
    assert q.read(DONE) == 2 and q.read(BUSY) == 0
    assert q.read(STIMULUS + 4) == 2
    assert q.read(STIMULUS + 8) == q.read(STIMULUS + 12) == 0
    print("G13B1_UNROUTED_PA26_EDGES_NO_FAKE_CAPTURE_DMA=PASS")
    q.write(CLEAR, 1)
    assert q.read(NUM) == q.read(DONE) == 0

    # Independent board test harness sets native capture/DMA registers.
    # This is NOT a guest DShot decode acceptance claim.
    init(q)
    q.write(PINCM_PA26, 0x00040083)   # actual TI TIMG4_0_CCP0
    q.write(TIMER + 0x1088, 1 << 8)   # GEN_EVENT1/CCU0
    q.write(TRIG, 34)                  # TIMG4 GEN_EVENT1 -> DMA CH2

    frame = dshot_frame(1000)
    # All payload is a physical wire-level rising/falling EDGE table.
    # No encoded frame is ever passed to the QEMU model.
    add_edge(q, 10_000, 1)  # rest low, first rising edge after idle
    for bit in range(15, -1, -1):
        high = 125 if (frame >> bit) & 1 else 63
        if bit != 15:
            add_edge(q, (167 - prev_high) * 10, 1)
        add_edge(q, high * 10, 0)
        prev_high = high
    # NB: this loop schedules 32 edges: first rising, 16 falling,
    # 15 subsequent rising edges, no host-written SRAM.
    assert q.read(NUM) == 32
    assert q.read(DONE) == 0
    q.write(START, 1)
    assert q.read(BUSY) == 1
    # Each scheduled edge has a unique nonzero QEMU virtual-clock deadline.
    q.cmd("clock_step 1_000_000")
    assert q.read(BUSY) == 0
    assert q.read(DONE) == q.read(NUM) == 32
    assert q.read(LINE) == 0
    assert q.read(STIMULUS + 8) == 32, "No genuine TIMG4 captures"
    assert q.read(STIMULUS + 12) == 32, "No genuine DMA CH2 beats"
    assert q.read(SIZE) == 0
    timestamps = [q.read(BUFFER + i * 4) for i in range(32)]
    assert all(a < b for a, b in zip(timestamps, timestamps[1:])), timestamps
    decoded = 0
    for index in range(16):
        width = timestamps[2 * index + 1] - timestamps[2 * index]
        assert width in (63, 125), (index, width)
        decoded = (decoded << 1) | int(width >= 94)
    assert decoded == frame, (hex(decoded), hex(frame))
    assert q.read(CC0) == timestamps[-1]
    print(f"G13B1_QEMU_VIRTUAL_WIRE_DSHOT600_DMA32=0x{decoded:04x} PASS")
    print("PASS_G13B1_NO_GUEST_BUFFER_OVERRIDE_NO_PHANTOM_IRQ")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    a = p.parse_args()
    for v in (a.qemu, a.elf):
        if not v.is_file():
            p.error(f"Missing file: {v}")
    run(a.qemu.resolve(), a.elf.resolve(), True, test_wave)
    print("PASS_G13B1_EXTERNAL_PA26_WAVEFORM_QTEST_ONLY")


if __name__ == "__main__":
    main()
