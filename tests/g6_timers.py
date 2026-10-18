#!/usr/bin/env python3
"""G6 TIMG4 DShot-capture clock / TIMG12 commutation timebase regression.

The clock/timer/IRQ hardware is modeled; PA26 edges, DMA0 Channel2 and
MCPWM output have NOT yet been connected to the motor plant.
"""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

TIMG4, TIMG12 = 0x40180000, 0x40188000
CLKDIV, CLKSEL = 0x1000, 0x1008
CCLKCTL, CPS = 0x1108, 0x110c
IMASK, RIS, MIS, ICLR = 0x1028, 0x1030, 0x1038, 0x1048
EVT1_IMASK, EVT1_RIS = 0x1088, 0x1090
CTR, CTRCTL, LOAD = 0x1800, 0x1804, 0x1808
CC0, CCCTL0 = 0x1810, 0x1830
PWREN, RSTCTL = 0x800, 0x804
RUN_UP_PERIODIC = 0x20000023
RUN_UP_ONESHOT = 0x20000021

def with_qtest(qemu, elf, sim, verify):
    with tempfile.TemporaryDirectory(prefix="am13e-g6-") as folder:
        socket_path = os.path.join(folder, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(socket_path)
            listener.listen(1)
            listener.settimeout(15)
            proc = subprocess.Popen([
                str(qemu), "-machine", "am13e23019,accel=qtest,esc-sim=" +
                ("on" if sim else "off"),
                "-kernel", str(elf), "-display", "none", "-serial", "none",
                "-monitor", "none", "-qtest", f"unix:path={socket_path}"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                conn, _ = listener.accept()
                with conn:
                    verify(QTest(conn))
            finally:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                stderr = proc.stderr.read()
                proc.stderr.close()
    return stderr

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", required=True, type=Path)
    parser.add_argument("--elf", required=True, type=Path)
    args = parser.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for path in (qemu, elf):
        if not path.is_file():
            parser.error(f"File not found: {path}")

    def functional(q):
        for timer in (TIMG4, TIMG12):
            assert q.read(timer + PWREN) == 0
            assert q.read(timer + CLKSEL) == 0
            q.write(timer + PWREN, 0x26000001)
            assert q.read(timer + PWREN) == 1
            # Exact TI DriverLib setClockConfig(BUSCLK, /1, CPS=0)
            q.write(timer + CLKSEL, 8)
            q.write(timer + CLKDIV, 0)
            q.write(timer + CPS, 0)
            q.write(timer + CCLKCTL, 1)
            assert q.read(timer + CLKSEL) == 8
            assert q.read(timer + CCLKCTL) == 1
            assert q.read(timer + CTRCTL) == 0
            assert q.read(timer + MIS) == 0
        print("G6_TIMG4_TIMG12_BUSCLK_CONFIG=PASS")

        # TIMG4: capture registers retain mode/config only; no DShot
        # input waveform means no fabricated capture or DMA event.
        q.write(TIMG4 + LOAD, 0xffff)
        q.write(TIMG4 + CCCTL0, 0x80000000)
        assert q.read(TIMG4 + CCCTL0) == 0x80000000
        assert q.read(TIMG4 + CC0) == 0
        assert q.read(TIMG4 + EVT1_RIS) == 0
        q.write(TIMG4 + EVT1_IMASK, 1)
        q.write(TIMG4 + CTRCTL, RUN_UP_PERIODIC)
        q.cmd("clock_step 655359")
        assert q.read(TIMG4 + RIS) == 0
        q.cmd("clock_step 1")
        assert q.read(TIMG4 + RIS) & 1
        assert q.read(TIMG4 + EVT1_RIS) & 1
        assert q.read(TIMG4 + CTRCTL) & 1
        print("G6_TIMG4_PERIODIC_ZERO_EVENT_NO_FALSE_CAPTURE=PASS")

        # TIMG12: one-shot commutation delay must not fire until the
        # programmed virtual 100MHz counter reaches zero.
        q.write(TIMG12 + LOAD, 99)
        q.write(TIMG12 + IMASK, 1)
        q.write(TIMG12 + CTRCTL, RUN_UP_ONESHOT)
        assert q.read(TIMG12 + RIS) == 0
        q.cmd("clock_step 999")
        assert q.read(TIMG12 + RIS) == 0
        q.cmd("clock_step 1")
        assert q.read(TIMG12 + RIS) == 1
        assert q.read(TIMG12 + MIS) == 1
        assert (q.read(TIMG12 + CTRCTL) & 1) == 0
        assert (q.read(TIMG12 + CTR) & 0xffff) == 99
        q.write(TIMG12 + ICLR, 1)
        assert q.read(TIMG12 + RIS) == 0
        assert q.read(TIMG12 + MIS) == 0
        assert q.read(TIMG4 + RIS) & 1  # IRQ source is per peripheral
        print("G6_TIMG12_ONE_SHOT_IRQ_ZERO_AND_CLEAR=PASS")

        q.write(TIMG4 + RSTCTL, 0xB1000003)
        assert q.read(TIMG4 + CTRCTL) == 0
        assert q.read(TIMG4 + RIS) == 0
        assert q.read(TIMG12 + MIS) == 0
        print("PASS_G6_GPTIMER_VIRTUAL_TIME_COUNTER_AND_IRQ")

    with_qtest(qemu, elf, True, functional)

    def strict(q):
        q.write(TIMG4 + PWREN, 0x26000001)
        q.read(TIMG4 + CLKSEL)

    err = with_qtest(qemu, elf, False, strict)
    assert "G6_UNMODELED_TIMG4 read" in err, err
    print("PASS_G6_STRICT_TIMG4_FAIL_CLOSED")

if __name__ == "__main__":
    main()
