#!/usr/bin/env python3
"""G2c QTest: SYSCTL MCLKCFG documented divider RMW; no PLL-ready spoofing."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

MCLKCFG = 0x400B0104
CLKSTATUS = 0x400B0204
INITIAL = 0x07000200
INITIAL_STATUS = 0x00007000

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    args = parser.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for f in (qemu, elf):
        if not f.is_file():
            parser.error(f"Missing file: {f}")
    with tempfile.TemporaryDirectory(prefix="am13e-g2c-") as tmp:
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
                    assert q.read(MCLKCFG) == INITIAL
                    assert q.read(CLKSTATUS) == INITIAL_STATUS
                    # Exercise a legitimate divider transition and restore.
                    # The Firmware-selected DIV_2_DIV_4 is the reset code 7.
                    q.write(MCLKCFG, 0x03000200)
                    value = q.read(MCLKCFG)
                    print(f"G2_MCLKDIVCFG_DIV1_DIV4=0x{value:08x}")
                    assert value == 0x03000200
                    q.write(MCLKCFG, INITIAL)
                    value = q.read(MCLKCFG)
                    status = q.read(CLKSTATUS)
                    print(f"G2_MCLKDIVCFG_DIV2_DIV4=0x{value:08x} "
                          f"CLKSTATUS=0x{status:08x}")
                    assert value == INITIAL
                    assert status == INITIAL_STATUS, "Clock ready must not be synthesized"
                    # An unmodeled USEHSCLK write must NOT take effect.
                    q.write(MCLKCFG, INITIAL | (1 << 16))
                    value = q.read(MCLKCFG)
                    print(f"G2_MCLKDIVCFG_REJECT_HSCLK=0x{value:08x}")
                    assert value == INITIAL, "Unsupported source change accepted"
                    print("PASS_G2C_MCLKDIVCFG_ONLY")
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
