#!/usr/bin/env python3
"""G2a QTest: grounded SYSCTL reset snapshots, without running guest code."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    args = p.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for f in (qemu, elf):
        if not f.is_file():
            p.error("missing file: " + str(f))
    with tempfile.TemporaryDirectory(prefix="am13e-g2a-") as tmp:
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
                    for name, addr, expected in (
                        ("MCLKCFG", 0x400B0104, 0x07000200),
                        ("CLKSTATUS", 0x400B0204, 0x00007000),
                    ):
                        observed = q.read(addr)
                        print(f"G2_SYSCTL_RESET {name}=0x{observed:08x} "
                              f"at 0x{addr:08x}")
                        assert observed == expected, (
                            f"{name}: expected 0x{expected:08x}, "
                            f"got 0x{observed:08x}")
                    print("PASS_G2A_SYSCTL_RESET_SNAPSHOT_ONLY")
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
