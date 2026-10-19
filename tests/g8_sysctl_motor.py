#!/usr/bin/env python3
"""G8: SYSCTL PWM time-base sync and shared motor peripheral power/reset.

This checks digital SYSCTL setup only. MCPWM output/phase timing,
ECAP1 BEMF feedback, and comparator/plant events are NOT produced here.
"""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

SYS = 0x400AF000
PERCLKCR = SYS + 0x148C
POWER = SYS + 0x1424
RST_ASSERT = SYS + 0x1428
RST_CLEAR = SYS + 0x142C
STAT = SYS + 0x1430
PWM4 = 1 << 9
CMPSS0 = 1 << 10
ECAP1 = 1 << 4
XBAR = 1 << 14
ALL = (1 << 15) - 1
ANALOG = (0x1444, 0x144c, 0x1450, 0x1454,
          0x1480, 0x1484, 0x1488)

def run(qemu, elf, sim, check):
    with tempfile.TemporaryDirectory(prefix="am13e-g8-") as td:
        sockpath = os.path.join(td, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(sockpath)
            server.listen(1)
            server.settimeout(15)
            proc = subprocess.Popen(
                [str(qemu), "-machine",
                 "am13e23019,accel=qtest,esc-sim=" + (
                     "on" if sim else "off"),
                 "-kernel", str(elf), "-display", "none",
                 "-serial", "none", "-monitor", "none",
                 "-qtest", f"unix:path={sockpath}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, text=True)
            try:
                connection, _ = server.accept()
                with connection:
                    check(QTest(connection))
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", type=Path, required=True)
    ap.add_argument("--elf", type=Path, required=True)
    args = ap.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for p in (qemu, elf):
        if not p.is_file():
            ap.error(f"Missing {p}")

    def sim(q):
        assert q.read(PERCLKCR) == 0
        assert q.read(POWER) == 0
        assert q.read(STAT) == 0
        q.write(PERCLKCR, 1)
        assert q.read(PERCLKCR) == 1
        q.write(PERCLKCR, 0)
        assert q.read(PERCLKCR) == 0
        q.write(PERCLKCR, 2)  # Reserved bit; reject
        assert q.read(PERCLKCR) == 0
        print("G8_PERCLKCR_TBCLKSYNC_ENABLE_DISABLE=PASS")

        # SDK DL_SYSCTL_enablePower uses RMW, KEY=0x26.
        q.write(POWER, PWM4)
        assert q.read(POWER) == 0
        q.write(POWER, 0x26000000 | PWM4)
        assert q.read(POWER) == PWM4
        q.write(POWER, q.read(POWER) | 0x26000000 | CMPSS0)
        assert q.read(POWER) == PWM4 | CMPSS0
        q.write(POWER, q.read(POWER) | 0x26000000 | ECAP1 | XBAR)
        assert q.read(POWER) == PWM4 | CMPSS0 | ECAP1 | XBAR
        q.write(POWER, 0x26008000 | PWM4)
        assert q.read(POWER) == PWM4 | CMPSS0 | ECAP1 | XBAR
        q.write(POWER, 0x26000000 | ECAP1)
        assert q.read(POWER) == ECAP1
        q.write(POWER, 0x26000000)
        assert q.read(POWER) == 0
        print("G8_MCPERIPH_PWM4_ECAP1_CMPSS0_XBAR_POWER=PASS")

        # SDK DL_SYSCTL_resetPeripheral clears sticky then asserts.
        q.write(RST_ASSERT, PWM4)
        assert q.read(STAT) == 0
        q.write(RST_ASSERT, 0xB1000000 | PWM4 | CMPSS0)
        assert q.read(STAT) == PWM4 | CMPSS0
        assert q.read(RST_ASSERT) == 0  # write-only
        q.write(RST_CLEAR, 0xB1000000 | PWM4)
        assert q.read(STAT) == CMPSS0
        q.write(RST_CLEAR, 0xB1000000 | CMPSS0)
        assert q.read(STAT) == 0
        q.write(RST_ASSERT, 0xB1008000)
        assert q.read(STAT) == 0
        print("G8_MCPERIPH_RESET_STICKY_AND_W1C=PASS")

        # These configuration registers don't create comparator events.
        for index, off in enumerate(ANALOG):
            value = 0x00000011 * (index + 1)
            q.write(SYS + off, value)
            assert q.read(SYS + off) == value
        assert q.read(STAT) == 0
        print("PASS_G8_SYSCTL_MOTOR_ROUTING_CONFIG_ONLY")

    run(qemu, elf, True, sim)

    def strict(q):
        q.read(PERCLKCR)
        q.write(PERCLKCR, 1)
    err = run(qemu, elf, False, strict)
    assert "G2_UNMODELED_SYSCTL read 0x400b048c" in err, err
    print("PASS_G8_STRICT_MODE_FAIL_CLOSED")

if __name__ == "__main__":
    main()
