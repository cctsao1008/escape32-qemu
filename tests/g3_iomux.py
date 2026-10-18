#!/usr/bin/env python3
"""G3b: exact TI IOMUX PINCM word semantics for ESC pin routing."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path

from g0_memory import QTest

IOMUX = 0x400CC000
PA22_NFAULT = 22
PA26_DSHOT = 26
PA8_PWM_UH = 8
PB13_GATE = 45
PINCM_COUNT = 108


def reg(index):
    return IOMUX + 4 * index


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", required=True, type=Path)
    parser.add_argument("--elf", required=True, type=Path)
    args = parser.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for path in (qemu, elf):
        if not path.is_file():
            parser.error(f"Missing file: {path}")
    with tempfile.TemporaryDirectory(prefix="am13e-g3b-") as tmp:
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
                conn, _ = listener.accept()
                with conn:
                    q = QTest(conn)
                    for index in (0, PA22_NFAULT, PA26_DSHOT,
                                  PA8_PWM_UH, PB13_GATE, PINCM_COUNT - 1):
                        assert q.read(reg(index)) == 0
                    print("G3_IOMUX_RESET_PINCM108_ZERO=PASS")

                    # Actual observed ELF fault instruction wrote this
                    # value to PA22: PF=GPIO1, PC=1, INENA=1.
                    q.write(reg(PA22_NFAULT), 0x00040081)
                    assert q.read(0x400CC058) == 0x00040081
                    print("G3_IOMUX_PA22_NFAULT=0x00040081")

                    # GPIO peripheral command input and PWM alternate pad.
                    q.write(reg(PA26_DSHOT), 0x00040082)
                    q.write(reg(PA8_PWM_UH), 0x00000086)
                    q.write(reg(PB13_GATE), 0x00040081)
                    assert q.read(reg(PA26_DSHOT)) == 0x00040082
                    assert q.read(reg(PA8_PWM_UH)) == 0x00000086
                    assert q.read(reg(PB13_GATE)) == 0x00040081
                    assert q.read(reg(PA22_NFAULT)) == 0x00040081
                    print("G3_IOMUX_DSHOT_PWM_GPIO_PINMUX_READBACK=PASS")

                    # SDK RMW: input disable and restore, preserving PF/PC.
                    q.write(reg(PA22_NFAULT), 0x00000081)
                    assert q.read(reg(PA22_NFAULT)) == 0x00000081
                    q.write(reg(PA22_NFAULT), 0x00040081)
                    assert q.read(reg(PA22_NFAULT)) == 0x00040081

                    # Reserved/read-only WAKESTAT must not be invented.
                    q.write(reg(PA22_NFAULT), 0x00042081)
                    assert q.read(reg(PA22_NFAULT)) == 0x00040081
                    q.write(reg(PA22_NFAULT), 0x80040081)
                    assert q.read(reg(PA22_NFAULT)) == 0x00040081

                    # Upper PINCM index remains addressable; slot 108
                    # (outside the documented 0..107) remains rejected.
                    q.write(reg(PINCM_COUNT - 1), 0x00000081)
                    assert q.read(reg(PINCM_COUNT - 1)) == 0x00000081
                    q.write(reg(PINCM_COUNT), 0x00000081)
                    assert q.read(reg(PINCM_COUNT - 1)) == 0x00000081
                    print("PASS_G3B_IOMUX_PINCM_CONTROL_ONLY")
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
