#!/usr/bin/env python3
"""G5: WWDT0 valid-input timeout state, power/reset, strict gating."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

BASE = 0x400d0000
PWREN, RSTCTL, PSTAT = BASE+0x800, BASE+0x804, BASE+0x814
CTL0, CTL1, FEED, RUN = BASE+0x1100, BASE+0x1104, BASE+0x1108, BASE+0x110c
SYSTEMCFG = 0x400b0180


def run_qtest(qemu, elf, sim, inspect):
    with tempfile.TemporaryDirectory(prefix="am13e-g5-") as directory:
        path = os.path.join(directory, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(path)
            server.listen(1)
            server.settimeout(15)
            proc = subprocess.Popen([
                str(qemu), "-machine",
                "am13e23019,accel=qtest,esc-sim=" +
                ("on" if sim else "off"),
                "-kernel", str(elf), "-display", "none", "-serial", "none",
                "-monitor", "none", "-qtest", f"unix:path={path}",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                sock, _ = server.accept()
                with sock:
                    inspect(QTest(sock))
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
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    args = parser.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for f in (qemu, elf):
        if not f.is_file():
            parser.error(f"Missing {f}")

    def functional(q):
        assert q.read(PWREN) == 0
        assert q.read(PSTAT) == 0
        assert q.read(RUN) == 0
        q.write(PWREN, 1)  # no unlock KEY
        assert q.read(PWREN) == 0
        q.write(PWREN, 0x26000001)
        assert q.read(PWREN) == 1
        assert q.read(RUN) == 0  # required by input_watchdog_prepare()
        q.write(SYSTEMCFG, 0x1b000001)  # NMI selection
        assert q.read(SYSTEMCFG) == 1
        q.write(SYSTEMCFG, 0x1b000000)  # firmware's reset selection
        assert q.read(SYSTEMCFG) == 0
        print("G5_WWDT_PREPARE_UNARMED=PASS")

        q.write(CTL0, 0x00000030)  # invalid KEY
        assert q.read(RUN) == 0
        q.write(CTL0, 0xc9000030)  # PERIOD=2^15, DIV=1
        assert q.read(CTL0) == 0x30
        assert q.read(RUN) == 1
        q.write(CTL1, 0xbe000000)
        assert q.read(CTL1) == 0
        q.cmd("clock_step 500000000")
        assert q.read(RUN) == 1
        q.write(FEED, 0xa7)
        q.cmd("clock_step 999999999")
        assert q.read(RUN) == 1
        q.cmd("clock_step 1")
        assert q.read(RUN) == 0
        print("G5_WWDT_ARM_FEED_AND_TIMEOUT=PASS")
        q.write(RSTCTL, 0xb1000003)
        assert q.read(PSTAT) == 0x00010000
        assert q.read(RUN) == 0
        q.write(RSTCTL, 0xb1000002)
        assert q.read(PSTAT) == 0
        print("PASS_G5_WWDT_SOFTWARE_STATE_AND_RESET")

    log = run_qtest(qemu, elf, True, functional)
    assert "ESC_SIM_WWDT_EXPIRED" in log, log
    print("PASS_G5_EXPIRED_EVENT_NOT_HARDWARE_BOOTRST")

    def strict(q):
        q.read(PWREN)
        q.write(PWREN, 0x26000001)

    strict_log = run_qtest(qemu, elf, False, strict)
    assert "G4_UNMODELED_GPRCM WWDT0" in strict_log, strict_log
    print("PASS_G5_STRICT_FAIL_CLOSED")


if __name__ == "__main__":
    main()
