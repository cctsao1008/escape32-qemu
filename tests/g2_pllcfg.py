#!/usr/bin/env python3
"""G2h QTest: SYSPLLCFG0/1 RMW without fabricating PLLGOOD."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

CFG0 = 0x400B0120
CFG1 = 0x400B0124
HSCLKEN = 0x400B0108
CLKSTATUS = 0x400B0204

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", required=True, type=Path)
    ap.add_argument("--elf", required=True, type=Path)
    args = ap.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for p in (qemu, elf):
        if not p.is_file():
            ap.error(f"Missing file: {p}")
    with tempfile.TemporaryDirectory(prefix="am13e-g2h-") as tmp:
        path = os.path.join(tmp, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(path)
            listener.listen(1)
            listener.settimeout(15)
            proc = subprocess.Popen([
                str(qemu), "-machine", "am13e23019,accel=qtest",
                "-kernel", str(elf), "-display", "none", "-serial", "none",
                "-monitor", "none", "-qtest", f"unix:path={path}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                sock, _ = listener.accept()
                with sock:
                    q = QTest(sock)
                    cfg0, cfg1 = q.read(CFG0), q.read(CFG1)
                    print(f"G2_PLLCFG_RESET CFG0=0x{cfg0:08x} CFG1=0x{cfg1:08x}")
                    assert (cfg0, cfg1) == (0x30, 0x2300)
                    assert q.read(CLKSTATUS) == 0x7000

                    # XTAL reference, CLK0 on, CLK1 off. Exercise RMW.
                    q.write(CFG0, 0x00000011)
                    q.write(CFG0, 0x00001111)  # both RDIV fields legal
                    assert q.read(CFG0) == 0x00001111
                    q.write(CFG0, 0x00000011)
                    assert q.read(CFG0) == 0x00000011

                    # Firmware: PDIV /2, QDIV 31, VCO 400MHz,
                    # CLK0 output /2 => 200MHz nominal configuration.
                    q.write(CFG1, 0x00001f00)
                    q.write(CFG1, 0x00001f01)
                    assert q.read(CFG1) == 0x00001f01
                    print(f"G2_PLLCFG_200M_REQUEST CFG0=0x{q.read(CFG0):08x} "
                          f"CFG1=0x{q.read(CFG1):08x}")
                    assert q.read(CLKSTATUS) == 0x7000

                    # Invalid QDIV, reserved-bit changes are rejected.
                    q.write(CFG1, 0x00000001)
                    assert q.read(CFG1) == 0x00001f01
                    q.write(CFG1, 0x00001f81)
                    assert q.read(CFG1) == 0x00001f01
                    q.write(CFG0, 0x80000011)
                    assert q.read(CFG0) == 0x00000011

                    # SYSPLL configuration is blocked after enable request.
                    q.write(HSCLKEN, 0x00000100)
                    assert q.read(HSCLKEN) == 0x00000100
                    q.write(CFG0, 0x00000031)
                    q.write(CFG1, 0x00002300)
                    assert (q.read(CFG0), q.read(CFG1)) == (0x11, 0x1f01)
                    assert q.read(CLKSTATUS) == 0x7000
                    print("G2_PLLCFG_ENABLE_NO_LOCK CLKSTATUS=0x00007000")
                    q.write(HSCLKEN, 0)
                    q.write(CFG1, 0x00002300)
                    assert q.read(CFG1) == 0x00002300
                    print("PASS_G2H_SYSPLL_CONFIG_ONLY")
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

if __name__ == "__main__":
    main()
