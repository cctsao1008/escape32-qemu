#!/usr/bin/env python3
"""G4a QTest: shared ADC/TIMG GPRCM reset/power, no ADC fake samples."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

PERIPHERALS = [
    (0x40000000, "ADC0"),
    (0x40002000, "ADC1"),
    (0x40004000, "ADC2"),
    (0x40180000, "TIMG4"),
    (0x40188000, "TIMG12"),
]

def scenario(qemu, elf, simulate):
    with tempfile.TemporaryDirectory(prefix="am13e-g4a-") as directory:
        sockpath = os.path.join(directory, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(sockpath)
            listener.listen(1)
            listener.settimeout(15)
            proc = subprocess.Popen([
                str(qemu), "-machine",
                "am13e23019,accel=qtest,esc-sim=" +
                ("on" if simulate else "off"),
                "-kernel", str(elf), "-display", "none", "-serial", "none",
                "-monitor", "none", "-qtest", f"unix:path={sockpath}"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                conn, _ = listener.accept()
                with conn:
                    q = QTest(conn)
                    if not simulate:
                        q.write(0x40000804, 0xB1000003)
                        q.read(0x40000814)
                    else:
                        for base, name in PERIPHERALS:
                            pwren, rstctl, stat = base + 0x800, base + 0x804, base + 0x814
                            assert q.read(pwren) == 0, name
                            assert q.read(stat) == 0, name
                            q.write(pwren, 1)             # invalid password
                            assert q.read(pwren) == 0, name
                            q.write(rstctl, 3)            # invalid password
                            assert q.read(stat) == 0, name
                            q.write(rstctl, 0xB1000003)
                            assert q.read(stat) == 0x00010000, name
                            q.write(pwren, 0x26000001)
                            assert q.read(pwren) == 1, name
                            q.write(rstctl, 0xB1000002)
                            assert q.read(stat) == 0, name
                            q.write(pwren, 0x26000000)
                            assert q.read(pwren) == 0, name
                            print(f"G4_GPRCM_{name}_RESET_POWER=PASS")
                        # Regression: a powered ADC's data/status path
                        # must remain unmodeled until an ADC sequencer
                        # and sensor/plant are connected.
                        q.write(0x40000800, 0x26000001)
                        q.read(0x40001000)
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
    if simulate:
        # An unassigned MMIO read may report a guest transaction
        # failure without writing QEMU stderr. The GPRCM is deliberately
        # only a 0x20-byte window; do not infer ADC readiness.
        print("PASS_G4A_ADC_TIMG_GPRCM_ONLY")
    else:
        assert "G4_UNMODELED_GPRCM ADC0" in stderr, stderr
        print("PASS_G4A_STRICT_GPRCM_FAIL_CLOSED")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", type=Path, required=True)
    ap.add_argument("--elf", type=Path, required=True)
    args = ap.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for file in (qemu, elf):
        if not file.is_file():
            ap.error(f"Missing file: {file}")
    scenario(qemu, elf, True)
    scenario(qemu, elf, False)


if __name__ == "__main__":
    main()
