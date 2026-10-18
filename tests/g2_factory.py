#!/usr/bin/env python3
"""G2i: Factory ROM window transport only; synthetic words are NOT calibration."""
import argparse
import os
import socket
import struct
import subprocess
import tempfile
from pathlib import Path

from g0_memory import QTest

FACTORY0 = 0x60111028
FACTORY1 = 0x6011102C
# Transport sentinels are deliberately *not* TI factory tuning values.
TEST_WORD0 = 0xA5B6C7D8
TEST_WORD1 = 0xD8C7B6A5


def run_qtest(qemu, elf, fixture, check):
    with tempfile.TemporaryDirectory(prefix="am13e-g2i-") as tmp:
        path = os.path.join(tmp, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(path)
            listener.listen(1)
            listener.settimeout(15)
            machine = "am13e23019,accel=qtest"
            if fixture is not None:
                machine += ",factory-pll-file=" + str(fixture)
            proc = subprocess.Popen([
                str(qemu), "-machine", machine, "-kernel", str(elf),
                "-display", "none", "-serial", "none", "-monitor", "none",
                "-qtest", f"unix:path={path}",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                conn, _ = listener.accept()
                with conn:
                    check(QTest(conn))
            finally:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    _, err = proc.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    _, err = proc.communicate(timeout=3)
            return err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", type=Path, required=True)
    ap.add_argument("--elf", type=Path, required=True)
    args = ap.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for file in (qemu, elf):
        if not file.is_file():
            ap.error("Missing file: " + str(file))

    # No fixture: the FACTORY read must be fail-closed and logged.
    def check_absent(q):
        q.read(FACTORY0)  # QTest's data word is not a MEMTX_OK indication.
    stderr = run_qtest(qemu, elf, None, check_absent)
    assert "G2_FACTORY_UNAVAILABLE read 0x60111028" in stderr, stderr
    print("PASS_G2I_FACTORY_UNPROVISIONED_REJECTED")

    with tempfile.TemporaryDirectory(prefix="am13e-g2i-input-") as tmp:
        fixture = Path(tmp) / "transport-sentinels.bin"
        fixture.write_bytes(struct.pack("<II", TEST_WORD0, TEST_WORD1))

        def check_transport(q):
            got0, got1 = q.read(FACTORY0), q.read(FACTORY1)
            print(f"G2_FACTORY_TRANSPORT_WORDS word0=0x{got0:08x} "
                  f"word1=0x{got1:08x} SYNTHETIC_NOT_CALIBRATION")
            assert (got0, got1) == (TEST_WORD0, TEST_WORD1)
            # FACTORY is read-only even when an input is supplied.
            q.write(FACTORY0, 0)
            q.write(FACTORY1, 0)
            assert (q.read(FACTORY0), q.read(FACTORY1)) == (
                TEST_WORD0, TEST_WORD1)
        run_qtest(qemu, elf, fixture, check_transport)
        print("PASS_G2I_EXPLICIT_FACTORY_READ_ONLY_TRANSPORT")

        # Wrong length must fail to initialize, not silently pad data.
        invalid = Path(tmp) / "invalid.bin"
        invalid.write_bytes(b"\x00\x01\x02\x03")
        proc = subprocess.run([
            str(qemu), "-machine",
            "am13e23019,accel=qtest,factory-pll-file=" + str(invalid),
            "-kernel", str(elf), "-display", "none", "-serial", "none",
            "-monitor", "none", "-qtest", "stdio",
        ], input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=10)
        assert proc.returncode != 0, "Invalid fixture unexpectedly accepted"
        assert b"G2_FACTORY_FILE_INVALID" in proc.stderr, proc.stderr
        print("PASS_G2I_INVALID_FIXTURE_SIZE_REJECTED")


if __name__ == "__main__":
    main()
