#!/usr/bin/env python3
"""G2g QTest: explicit virtual XTAL fixture + deterministic QEMU timer."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

HFCLKCLKCFG = 0x400B0110
XTALCR = 0x400B0474
CLKSTATUS = 0x400B0204
RESET_STATUS = 0x00007000
PENDING_STATUS = 0x00004000
READY_STATUS = 0x00004100
XTALTIME = 156
DELAY_NS = XTALTIME * 64000


def scenario(qemu, elf, virtual_xtal, scenario_name):
    with tempfile.TemporaryDirectory(prefix="am13e-g2g-") as tmp:
        path = os.path.join(tmp, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(path)
            listener.listen(1)
            listener.settimeout(15)
            machine = ("am13e23019,accel=qtest,xtal-present=" +
                       ("on" if virtual_xtal else "off"))
            proc = subprocess.Popen(
                [str(qemu), "-machine", machine, "-kernel", str(elf),
                 "-display", "none", "-serial", "none", "-monitor", "none",
                 "-qtest", f"unix:path={path}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                conn, _ = listener.accept()
                with conn:
                    q = QTest(conn)
                    assert q.read(CLKSTATUS) == RESET_STATUS
                    # Firmware writes XTALTIME before XTALCR.OSCOFF=0.
                    q.write(HFCLKCLKCFG, 0x10000000 | XTALTIME)
                    assert q.read(HFCLKCLKCFG) == 0x1000009c
                    q.write(XTALCR, 0)
                    initial = q.read(CLKSTATUS)
                    expected = PENDING_STATUS if virtual_xtal else RESET_STATUS
                    print(f"G2G_{scenario_name}_AFTER_ENABLE="
                          f"0x{initial:08x}")
                    assert initial == expected

                    # No host sleep. QTest advances QEMU_CLOCK_VIRTUAL
                    # by the precise documented duration in nanoseconds.
                    q.cmd(f"clock_step {DELAY_NS - 1}")
                    before = q.read(CLKSTATUS)
                    print(f"G2G_{scenario_name}_BEFORE_DEADLINE="
                          f"0x{before:08x}")
                    assert before == expected
                    q.cmd("clock_step 1")
                    after = q.read(CLKSTATUS)
                    print(f"G2G_{scenario_name}_AT_DEADLINE="
                          f"0x{after:08x}")
                    assert after == (READY_STATUS if virtual_xtal
                                     else RESET_STATUS)

                    # Disable the source and cancel any event.
                    q.write(XTALCR, 1)
                    off = q.read(CLKSTATUS)
                    print(f"G2G_{scenario_name}_AFTER_DISABLE=0x{off:08x}")
                    assert off == RESET_STATUS
                    q.cmd(f"clock_step {DELAY_NS * 2}")
                    assert q.read(CLKSTATUS) == RESET_STATUS

                    if virtual_xtal:
                        # A restarted oscillator remains OFF until
                        # the next independent startup-time deadline.
                        q.write(XTALCR, 0)
                        assert q.read(CLKSTATUS) == PENDING_STATUS
                        q.cmd(f"clock_step {DELAY_NS}")
                        assert q.read(CLKSTATUS) == READY_STATUS
                        # Start and cancel before expiry: no late GOOD.
                        q.write(XTALCR, 1)
                        q.write(XTALCR, 0)
                        q.cmd(f"clock_step {DELAY_NS // 2}")
                        q.write(XTALCR, 1)
                        q.cmd(f"clock_step {DELAY_NS}")
                        assert q.read(CLKSTATUS) == RESET_STATUS

                        # The monitor must be enabled before the
                        # XTAL request. Otherwise there is no GOOD.
                        q.write(HFCLKCLKCFG, XTALTIME)
                        q.write(XTALCR, 0)
                        assert q.read(CLKSTATUS) == RESET_STATUS
                        q.cmd(f"clock_step {DELAY_NS}")
                        assert q.read(CLKSTATUS) == RESET_STATUS
                        q.write(XTALCR, 1)
                        q.write(HFCLKCLKCFG, 0x10000000 | XTALTIME)

                        # With HFCLK_IN selected, an XTAL fixture must
                        # not masquerade as an external digital clock.
                        q.write(0x400B0108, 0x00010000)
                        q.write(XTALCR, 0)
                        assert q.read(CLKSTATUS) == RESET_STATUS
                        q.cmd(f"clock_step {DELAY_NS}")
                        assert q.read(CLKSTATUS) == RESET_STATUS
                        q.write(XTALCR, 1)
                        q.write(0x400B0108, 0x00000000)
                        print("PASS_G2G_MONITOR_AND_SOURCE_GATING")
                    print(f"PASS_G2G_{scenario_name}_VIRTUAL_XTAL")
            except Exception:
                if proc.poll() is not None:
                    print("QEMU stderr:", proc.stderr.read())
                raise
            finally:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                proc.stderr.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", required=True, type=Path)
    p.add_argument("--elf", required=True, type=Path)
    args = p.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for path in (qemu, elf):
        if not path.is_file():
            p.error("Missing file: " + str(path))
    scenario(qemu, elf, False, "ABSENT")
    scenario(qemu, elf, True, "PRESENT")


if __name__ == "__main__":
    main()
