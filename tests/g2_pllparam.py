#!/usr/bin/env python3
"""G2j SYSPLLPARAM: opaque factory word copy, no invented PLL startup."""
import argparse
import os
import socket
import struct
import subprocess
import tempfile
from pathlib import Path

from g0_memory import QTest

FACTORY0 = 0x60111028
FACTORY1 = 0x6011102c
PARAM0 = 0x400b0128
PARAM1 = 0x400b012c
HSCLKEN = 0x400b0108
CLKSTATUS = 0x400b0204
RESET0 = 0x810a0000
RESET1 = 0x0f00010f

# These words are deliberately arbitrary transport sentinels.
# They are not analog-accurate TI per-chip factory calibration.
SENTINEL0 = 0xa5b6c7d8
SENTINEL1 = 0xd8c7b6a5


def run_test(qemu, elf, fixture):
    with tempfile.TemporaryDirectory(prefix="am13e-g2j-") as tmp:
        socket_path = os.path.join(tmp, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(socket_path)
            listener.listen(1)
            listener.settimeout(15)
            cmd = [
                str(qemu), "-machine",
                "am13e23019,accel=qtest,factory-pll-file=" + str(fixture),
                "-kernel", str(elf), "-display", "none", "-serial", "none",
                "-monitor", "none", "-qtest", f"unix:path={socket_path}",
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True)
            try:
                connection, _ = listener.accept()
                with connection:
                    q = QTest(connection)
                    reset0, reset1 = q.read(PARAM0), q.read(PARAM1)
                    print(f"G2J_PARAM_RESET P0=0x{reset0:08x} "
                          f"P1=0x{reset1:08x}")
                    assert (reset0, reset1) == (RESET0, RESET1)
                    assert q.read(CLKSTATUS) == 0x7000

                    # Copy exactly what the original firmware reads
                    # from the separate physical FACTORY address space.
                    pair = (q.read(FACTORY0), q.read(FACTORY1))
                    assert pair == (SENTINEL0, SENTINEL1)
                    q.write(PARAM0, pair[0])
                    q.write(PARAM1, pair[1])
                    got = (q.read(PARAM0), q.read(PARAM1))
                    print(f"G2J_FACTORY_TO_PARAM_COPY P0=0x{got[0]:08x} "
                          f"P1=0x{got[1]:08x} SYNTHETIC_ONLY")
                    assert got == pair
                    assert q.read(CLKSTATUS) == 0x7000, (
                        "Factory register copies must not synthesize PLL lock")

                    # SYSPLLEN=1 blocks changes to both parameter regs.
                    q.write(HSCLKEN, 0x100)
                    assert q.read(HSCLKEN) == 0x100
                    q.write(PARAM0, RESET0)
                    q.write(PARAM1, RESET1)
                    assert (q.read(PARAM0), q.read(PARAM1)) == pair
                    assert q.read(CLKSTATUS) == 0x7000
                    print("G2J_PLL_ENABLED_NO_FAKE_LOCK CLKSTATUS=0x00007000")
                    q.write(HSCLKEN, 0)
                    assert q.read(HSCLKEN) == 0

                    # Model remains read/write while the PLL is off.
                    q.write(PARAM0, RESET0)
                    q.write(PARAM1, RESET1)
                    assert (q.read(PARAM0), q.read(PARAM1)) == (
                        RESET0, RESET1)
                    print("PASS_G2J_SYSPLL_PARAMETER_READ_WRITE_ONLY")
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", required=True, type=Path)
    parser.add_argument("--elf", required=True, type=Path)
    args = parser.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for f in (qemu, elf):
        if not f.is_file():
            parser.error(f"Missing file: {f}")
    with tempfile.TemporaryDirectory(prefix="am13e-g2j-input-") as tmp:
        fixture = Path(tmp) / "synthetic-transport-only.bin"
        fixture.write_bytes(struct.pack("<II", SENTINEL0, SENTINEL1))
        run_test(qemu, elf, fixture)


if __name__ == "__main__":
    main()
