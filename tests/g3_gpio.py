#!/usr/bin/env python3
"""G3a: GPIO GPRCM key/power/reset and basic digital port readback."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

GPIO0 = 0x400F0000
GPIO1 = 0x400F2000
GPIO3 = 0x400F6000

PWREN = 0x0800
RSTCTL = 0x0804
STAT = 0x0814
DOUT = 0x1280
DOUTSET = 0x1290
DOUTCLR = 0x12A0
DOUTTGL = 0x12B0
DOE = 0x12C0
DOESET = 0x12D0
DOECLR = 0x12E0
DIN = 0x1380


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    args = parser.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for path in (qemu, elf):
        if not path.is_file():
            parser.error(f"Missing file: {path}")

    with tempfile.TemporaryDirectory(prefix="am13e-g3a-") as tmp:
        sockpath = os.path.join(tmp, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(sockpath)
            listener.listen(1)
            listener.settimeout(15)
            proc = subprocess.Popen([
                str(qemu), "-machine", "am13e23019,accel=qtest,esc-sim=on",
                "-kernel", str(elf), "-display", "none", "-serial", "none",
                "-monitor", "none", "-qtest", f"unix:path={sockpath}",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                connection, _ = listener.accept()
                with connection:
                    q = QTest(connection)
                    for gpio in (GPIO0, GPIO1, GPIO3):
                        assert q.read(gpio + PWREN) == 0
                        assert q.read(gpio + STAT) == 0
                    print("G3_GPIO_RESET_GPIO0_GPIO1_GPIO3=unpowered")

                    # Missing power KEY must not enable an output port.
                    q.write(GPIO0 + PWREN, 1)
                    assert q.read(GPIO0 + PWREN) == 0
                    q.write(GPIO0 + PWREN, 0x26000001)
                    assert q.read(GPIO0 + PWREN) == 1
                    print("G3_GPIO0_PWR_KEY=0x26000001 ENABLED")

                    # Output and OE aliases have independently retained state.
                    q.write(GPIO0 + DOUT, 0x00000000)
                    q.write(GPIO0 + DOUTSET, 0x0000000F)
                    q.write(GPIO0 + DOESET, 0x0000000F)
                    assert q.read(GPIO0 + DOE) == 0xF
                    assert q.read(GPIO0 + DIN) == 0xF
                    q.write(GPIO0 + DOUTCLR, 0x00000002)
                    q.write(GPIO0 + DOUTTGL, 0x00000001)
                    assert q.read(GPIO0 + DIN) == 0xC
                    q.write(GPIO0 + DOECLR, 0x00000008)
                    assert q.read(GPIO0 + DIN) == 0x4
                    print("G3_GPIO0_DIGITAL_DIN=0x00000004")

                    # Reset must use the RSTCTL key and clear digital state.
                    q.write(GPIO0 + RSTCTL, 0x00000003)
                    assert q.read(GPIO0 + DIN) == 0x4
                    q.write(GPIO0 + RSTCTL, 0xB1000003)
                    assert q.read(GPIO0 + STAT) == 0x00010000
                    assert q.read(GPIO0 + DIN) == 0
                    assert q.read(GPIO0 + DOE) == 0
                    q.write(GPIO0 + RSTCTL, 0xB1000002)
                    assert q.read(GPIO0 + STAT) == 0
                    print("G3_GPIO0_RESET_STICKY_AND_CLEAR=PASS")

                    # Port isolation and valid power-down.
                    q.write(GPIO1 + PWREN, 0x26000001)
                    assert q.read(GPIO1 + PWREN) == 1
                    assert q.read(GPIO3 + PWREN) == 0
                    q.write(GPIO0 + PWREN, 0x26000000)
                    assert q.read(GPIO0 + PWREN) == 0
                    assert q.read(GPIO1 + PWREN) == 1
                    print("G3_GPIO_PORT_ISOLATION_AND_POWERDOWN=PASS")
                    print("PASS_G3A_GPIO_POWER_RESET_DIGITAL_ONLY")
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
