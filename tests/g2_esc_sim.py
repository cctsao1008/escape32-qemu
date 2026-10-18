#!/usr/bin/env python3
"""ESC-SIM: deterministic software-only startup; NOT analog PLL qualification."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

FACTORY0, FACTORY1 = 0x60111028, 0x6011102c
PARAM0, PARAM1 = 0x400b0128, 0x400b012c
XTALCR, XTALCFG = 0x400b0474, 0x400b0110
PLL0, PLL1 = 0x400b0120, 0x400b0124
HSCLKEN, HSCLKCFG = 0x400b0108, 0x400b010c
MCLKCFG, STATUS = 0x400b0104, 0x400b0204

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    args = p.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for path in (qemu, elf):
        if not path.is_file():
            p.error("Missing file: "+str(path))
    with tempfile.TemporaryDirectory(prefix="am13e-escsim-") as temp:
        path = os.path.join(temp, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(path)
            listener.listen(1)
            listener.settimeout(15)
            proc = subprocess.Popen([
                str(qemu), "-machine", "am13e23019,accel=qtest,esc-sim=on",
                "-kernel", str(elf), "-display", "none", "-serial", "none",
                "-monitor", "none", "-qtest", f"unix:path={path}",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                connection, _ = listener.accept()
                with connection:
                    q = QTest(connection)
                    assert q.read(STATUS) == 0x7000
                    trim = q.read(FACTORY0), q.read(FACTORY1)
                    assert trim == (0x810a0000, 0x0f00010f)
                    print("ESC_SIM_FACTORY=synthetic_defaults_NOT_TI_CALIBRATION")
                    q.write(XTALCFG, 0x1000009c)
                    q.write(XTALCR, 0)
                    assert q.read(STATUS) == 0x4000
                    q.cmd("clock_step 9984000")
                    assert q.read(STATUS) == 0x4100
                    q.write(PLL0, 0x11)
                    q.write(PLL1, 0x1f01)
                    q.write(PARAM0, trim[0])
                    q.write(PARAM1, trim[1])
                    q.write(HSCLKEN, 0x100)
                    assert not (q.read(STATUS) & 0x200)
                    q.cmd("clock_step 49999")
                    assert not (q.read(STATUS) & 0x200)
                    q.cmd("clock_step 1")
                    state = q.read(STATUS)
                    assert state & 0x200
                    assert state & 0x200000
                    assert not (state & 0x4000)
                    print(f"ESC_SIM_PLL_READY_STATUS=0x{state:08x} SYNTHETIC")
                    q.write(HSCLKCFG, 0)
                    q.write(MCLKCFG, 0x07010200)
                    assert q.read(MCLKCFG) == 0x07010200
                    assert q.read(STATUS) & 0x10
                    print("PASS_ESC_SIM_FUNCTIONAL_CLOCK_NOT_PHYSICAL_VALIDATION")
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
