#!/usr/bin/env python3
"""G2f QTest: HFCLKCLKCFG XTALTIME/monitor control; no clock-ready events."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path

from g0_memory import QTest

HFCLKCFG = 0x400B0110
CLKSTATUS = 0x400B0204
MCLKCFG = 0x400B0104
RESET = 0x10000000
CLOCK_RESET = 0x00007000
XTALTIME = 156  # 9.984ms at ~64us per step, not simulated elapsed time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    args = parser.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for path in (qemu, elf):
        if not path.is_file():
            parser.error("missing file: " + str(path))

    with tempfile.TemporaryDirectory(prefix="am13e-g2f-") as tmp:
        address = os.path.join(tmp, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(address)
            listener.listen(1)
            listener.settimeout(15)
            process = subprocess.Popen([
                str(qemu), "-machine", "am13e23019,accel=qtest",
                "-kernel", str(elf), "-display", "none", "-serial", "none",
                "-monitor", "none", "-qtest", f"unix:path={address}"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                conn, _ = listener.accept()
                with conn:
                    q = QTest(conn)
                    value = q.read(HFCLKCFG)
                    print(f"G2_HFCLKCFG_RESET=0x{value:08x}")
                    assert value == RESET, "HFCLKFLTCHK[28] resets to 1"
                    assert q.read(CLKSTATUS) == CLOCK_RESET

                    # SDK setXTALStartupTime(156) uses an RMW over [7:0].
                    q.write(HFCLKCFG, RESET | XTALTIME)
                    value = q.read(HFCLKCFG)
                    print(f"G2_HFCLKCFG_XTALTIME156=0x{value:08x}")
                    assert value == 0x1000009c
                    assert q.read(CLKSTATUS) == CLOCK_RESET

                    # The documented monitor bit may be cleared and set.
                    q.write(HFCLKCFG, XTALTIME)
                    value = q.read(HFCLKCFG)
                    print(f"G2_HFCLKCFG_MONITOR_OFF=0x{value:08x}")
                    assert value == 0x0000009c
                    q.write(HFCLKCFG, RESET | XTALTIME)
                    assert q.read(HFCLKCFG) == 0x1000009c

                    # Even after the XTAL enable request, the model
                    # has no virtual-time startup event and no GOOD.
                    q.write(0x400B0474, 0x00000000)
                    status = q.read(CLKSTATUS)
                    print(f"G2_HFCLKCFG_ENABLE_REQUEST_CLKSTATUS=0x{status:08x}")
                    assert status == CLOCK_RESET

                    # Refuse undefined reserved field writes.
                    q.write(HFCLKCFG, 0x9000009c)
                    value = q.read(HFCLKCFG)
                    print(f"G2_HFCLKCFG_REJECT_RESERVED=0x{value:08x}")
                    assert value == 0x1000009c
                    assert q.read(MCLKCFG) == 0x07000200
                    assert q.read(CLKSTATUS) == CLOCK_RESET
                    print("PASS_G2F_HFCLKCFG_CONTROL_ONLY")
            except Exception:
                if process.poll() is not None:
                    print("QEMU stderr:", process.stderr.read())
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
