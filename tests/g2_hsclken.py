#!/usr/bin/env python3
"""G2e QTest: HSCLKEN control readback, no oscillator/PLL-ready synthesis."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

HSCLKEN = 0x400B0108
MCLKCFG = 0x400B0104
CLKSTATUS = 0x400B0204
XTALCR = 0x400B0474
CLKSTATUS_RESET = 0x00007000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    args = parser.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for file in (qemu, elf):
        if not file.is_file():
            parser.error(f"Missing file: {file}")

    with tempfile.TemporaryDirectory(prefix="am13e-g2e-") as tmp:
        path = os.path.join(tmp, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(path)
            listener.listen(1)
            listener.settimeout(15)
            process = subprocess.Popen([
                str(qemu), "-machine", "am13e23019,accel=qtest",
                "-kernel", str(elf), "-display", "none", "-serial", "none",
                "-monitor", "none", "-qtest", f"unix:path={path}"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                sock, _ = listener.accept()
                with sock:
                    q = QTest(sock)
                    assert q.read(MCLKCFG) == 0x07000200
                    assert q.read(XTALCR) == 0x00000001
                    assert q.read(CLKSTATUS) == CLKSTATUS_RESET
                    initial = q.read(HSCLKEN)
                    print(f"G2_HSCLKEN_RESET=0x{initial:08x}")
                    assert initial == 0

                    # Selecting external digital input is a control bit,
                    # not proof of external clock presence.
                    q.write(HSCLKEN, 0x00010000)
                    got = q.read(HSCLKEN)
                    print(f"G2_HSCLKEN_USEEXTHFCLK=0x{got:08x}")
                    assert got == 0x00010000
                    assert q.read(CLKSTATUS) == CLKSTATUS_RESET

                    # A SYSPLL enable request is not PLL lock.
                    q.write(HSCLKEN, 0x00010100)
                    got = q.read(HSCLKEN)
                    status = q.read(CLKSTATUS)
                    print(f"G2_HSCLKEN_SYSPLLEN=0x{got:08x} "
                          f"CLKSTATUS=0x{status:08x}")
                    assert got == 0x00010100
                    assert status == CLKSTATUS_RESET

                    # Clear both controls; do not modify MCLK or XTAL.
                    q.write(HSCLKEN, 0x00000000)
                    assert q.read(HSCLKEN) == 0
                    assert q.read(MCLKCFG) == 0x07000200
                    assert q.read(XTALCR) == 0x00000001

                    # Reject write to reserved/undefined fields.
                    q.write(HSCLKEN, 0x80000000)
                    after = q.read(HSCLKEN)
                    print(f"G2_HSCLKEN_REJECT_RESERVED=0x{after:08x}")
                    assert after == 0
                    assert q.read(CLKSTATUS) == CLKSTATUS_RESET
                    print("PASS_G2E_HSCLKEN_CONTROL_ONLY")
            except Exception:
                if process.poll() is not None:
                    print(process.stderr.read())
                raise
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                process.stderr.close()


if __name__ == "__main__":
    main()
