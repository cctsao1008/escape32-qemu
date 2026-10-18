#!/usr/bin/env python3
"""G4b: 3x TI native ADC config, delayed SOC conversion and IRQ flags."""
import argparse
import os
import socket
import struct
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

ADCS = (0x40000000, 0x40002000, 0x40004000)
RESULTS = (0x4000a000, 0x4000b000, 0x4000c000)

def run(qemu, elf, fixture, verify):
    with tempfile.TemporaryDirectory(prefix="am13e-adc-") as tmp:
        sock = os.path.join(tmp, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(sock)
            server.listen(1)
            server.settimeout(15)
            cmd = ["am13e23019,accel=qtest,esc-sim=on"]
            if fixture is not None:
                cmd[0] += ",esc-sim-adc-fixture-file=" + str(fixture)
            proc = subprocess.Popen([
                str(qemu), "-machine", cmd[0], "-kernel", str(elf),
                "-display", "none", "-serial", "none", "-monitor", "none",
                "-qtest", f"unix:path={sock}",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                conn, _ = server.accept()
                with conn:
                    verify(QTest(conn))
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", type=Path, required=True)
    ap.add_argument("--elf", type=Path, required=True)
    args = ap.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for p in (qemu, elf):
        if not p.is_file():
            ap.error("Missing file: " + str(p))
    with tempfile.TemporaryDirectory(prefix="am13e-adc-fixture-") as tmp:
        fixture = Path(tmp) / "adc-raw.bin"
        table = [((adc + 1) * 1000 + ch) for adc in range(3)
                 for ch in range(32)]
        fixture.write_bytes(struct.pack("<96H", *table))

        def verify(q):
            # Mimic analog_sampling_backend.c initial program.
            for i, base in enumerate(ADCS):
                q.write(base + 0x804, 0xB1000003)
                q.write(base + 0x800, 0x26000001)
                q.write(base + 0x1004, 0x00000007)
                assert q.read(base + 0x1004) == 7
                for ch in range(16):
                    q.write(base + 0x104c + ch * 4, ch << 15)
                q.write(base + 0x1010, 0x00000082)
                q.write(base + 0x1320, 2)
                q.write(base + 0x1324, 0x80000000)
                q.write(base + 0x1000, 0x80)
                assert q.read(base + 0x1000) & 0x80
                assert q.read(base + 0x101c) == 0
                assert q.read(RESULTS[i]) == 0
            print("G4B_ADC0_1_2_CONFIG_RMW=PASS")

            for base in ADCS:
                q.write(base + 0x1324, 0xC0000000)
                assert q.read(base + 0x1000) & 0x2000
                assert q.read(base + 0x101c) == 0
            q.cmd("clock_step 19999")
            for base in ADCS:
                assert q.read(base + 0x101c) == 0
            q.cmd("clock_step 1")
            for i, base in enumerate(ADCS):
                assert not q.read(base + 0x1000) & 0x2000
                assert q.read(base + 0x101c) & 1
                val = q.read(RESULTS[i])
                assert (val & 0xffff) == (i + 1) * 1000
                assert (val >> 16) == (i + 1) * 1000 + 1
                q.write(base + 0x1024, 1)
                assert q.read(base + 0x101c) == 0
                print(f"G4B_ADC{i}_RESULT={val:#010x} IRQ_CLEAR=PASS")
            print("PASS_G4B_NATIVE_ADC_CONVERSION_EVENT_NOT_ANALOG_VALIDATION")

        run(qemu, elf, fixture, verify)

if __name__ == "__main__":
    main()
