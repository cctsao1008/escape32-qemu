#!/usr/bin/env python3
"""G2d: TI SYSCTL.XTALCR register semantics only, no fabricated clock-ready."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path

from g0_memory import QTest

XTALCR = 0x400B0474
CLKSTATUS = 0x400B0204
XTALCR_RESET = 0x00000001
CLKSTATUS_RESET = 0x00007000


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", required=True, type=Path)
    p.add_argument("--elf", required=True, type=Path)
    args = p.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for path in (qemu, elf):
        if not path.is_file():
            p.error("Missing file: " + str(path))

    with tempfile.TemporaryDirectory(prefix="am13e-g2d-") as tmp:
        address = os.path.join(tmp, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(address)
            listener.listen(1)
            listener.settimeout(15)
            process = subprocess.Popen([
                str(qemu), "-machine", "am13e23019,accel=qtest",
                "-kernel", str(elf), "-display", "none", "-serial", "none",
                "-monitor", "none", "-qtest", f"unix:path={address}",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                sock, _ = listener.accept()
                with sock:
                    q = QTest(sock)
                    got = q.read(XTALCR)
                    print(f"G2_XTALCR_RESET=0x{got:08x}")
                    assert got == XTALCR_RESET
                    # OSCOFF=1, SE=1: powered down, single-ended mode.
                    q.write(XTALCR, 0x00000003)
                    got = q.read(XTALCR)
                    print(f"G2_XTALCR_OFF_SE=0x{got:08x}")
                    assert got == 0x00000003
                    # Configure crystal mode, then request oscillator ON.
                    q.write(XTALCR, 0x00000001)
                    assert q.read(XTALCR) == 0x00000001
                    q.write(XTALCR, 0x00000000)
                    got = q.read(XTALCR)
                    status = q.read(CLKSTATUS)
                    print(f"G2_XTALCR_ENABLE_REQUEST=0x{got:08x} "
                          f"CLKSTATUS=0x{status:08x}")
                    assert got == 0
                    assert status == CLKSTATUS_RESET, (
                        "Clock GOOD must not appear without virtual-time oscillator")
                    # Reject attempts to write reserved fields.
                    q.write(XTALCR, 0x80000000)
                    got = q.read(XTALCR)
                    print(f"G2_XTALCR_REJECT_RESERVED=0x{got:08x}")
                    assert got == 0
                    print("PASS_G2D_XTALCR_CONTROL_ONLY")
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
