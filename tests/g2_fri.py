#!/usr/bin/env python3
"""G2b QTest: TI FRI.FRDCNTL reset and masked writes; no guest execution."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

FRI_FRDCNTL_ADDR = 0x40029000
RESET = 0x02000201

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    args = p.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for f in (qemu, elf):
        if not f.is_file():
            p.error("missing file: " + str(f))
    with tempfile.TemporaryDirectory(prefix="am13e-g2b-") as tmp:
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
                    qt = QTest(sock)
                    initial = qt.read(FRI_FRDCNTL_ADDR)
                    print(f"G2_FRI_RESET FRDCNTL=0x{initial:08x}")
                    assert initial == RESET, "TRM FRDCNTL reset mismatch"
                    # TI DL_FRI_setReadWaitStates(3): clear WS0 mode;
                    # then set the documented RWAIT field, preserving
                    # reserved bits and exercising readback after writes.
                    qt.write(FRI_FRDCNTL_ADDR, initial & ~1)
                    no_ws0 = qt.read(FRI_FRDCNTL_ADDR)
                    print(f"G2_FRI_DISABLE_WS0 FRDCNTL=0x{no_ws0:08x}")
                    assert no_ws0 == 0x02000200
                    qt.write(FRI_FRDCNTL_ADDR, (no_ws0 & ~0xF00) | 0x300)
                    wait3 = qt.read(FRI_FRDCNTL_ADDR)
                    print(f"G2_FRI_RWAIT3 FRDCNTL=0x{wait3:08x}")
                    assert wait3 == 0x02000300
                    print("PASS_G2B_FRI_REGISTER_SEMANTICS_ONLY")
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
