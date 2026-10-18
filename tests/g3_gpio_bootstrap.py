#!/usr/bin/env python3
"""G3c: bulk ESC-SIM GPIO bootstrap, interrupt masks and nFAULT bias."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

GPIO0 = 0x400f0000
GPIO1 = 0x400f2000
PWREN = 0x0800
DIN = 0x1380
NFAULT = 1 << 22
PA22_PINCM = 0x400cc058

def run(qemu, elf, sim, fault, checks):
    with tempfile.TemporaryDirectory(prefix="g3c-gpio-") as tmp:
        path = os.path.join(tmp, "qtest.sock")
        machine = "am13e23019,accel=qtest"
        if sim:
            machine += ",esc-sim=on"
        if fault:
            machine += ",esc-sim-nfault-asserted=on"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(path)
            server.listen(1)
            server.settimeout(15)
            proc = subprocess.Popen(
                [str(qemu), "-machine", machine, "-kernel", str(elf),
                 "-display", "none", "-serial", "none", "-monitor", "none",
                 "-qtest", f"unix:path={path}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                conn, _ = server.accept()
                with conn:
                    checks(QTest(conn))
            finally:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                err = proc.stderr.read()
                proc.stderr.close()
        return err

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", required=True, type=Path)
    ap.add_argument("--elf", required=True, type=Path)
    args = ap.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for x in (qemu, elf):
        if not x.is_file():
            ap.error(f"Missing file: {x}")

    def functional(q):
        q.write(GPIO0 + PWREN, 0x26000001)
        q.write(GPIO1 + PWREN, 0x26000001)
        assert q.read(GPIO0 + 0x1028) == 0
        assert q.read(GPIO0 + 0x1030) == 0
        assert q.read(GPIO0 + 0x1038) == 0
        assert q.read(GPIO0 + 0x1020) == 0
        q.write(GPIO0 + 0x1028, NFAULT)
        assert q.read(GPIO0 + 0x1028) == NFAULT
        assert q.read(GPIO0 + 0x1038) == 0
        q.write(GPIO0 + 0x1040, NFAULT)
        assert q.read(GPIO0 + 0x1030) == NFAULT
        assert q.read(GPIO0 + 0x1038) == NFAULT
        assert q.read(GPIO0 + 0x1020) == 23
        q.write(GPIO0 + 0x1048, NFAULT)
        assert q.read(GPIO0 + 0x1038) == 0
        print("G3C_CPU_INT_MASK_RIS_MIS_IIDX=PASS")

        # Exercise all three documented event families and simple
        # ancillary setup registers; no real edge/IRQ source implied.
        for base, mask in ((0x1050, 0x00000002),
                           (0x1080, 0x00400000)):
            q.write(GPIO0 + base + 8, mask)
            assert q.read(GPIO0 + base + 8) == mask
            q.write(GPIO0 + base + 0x20, mask)
            assert q.read(GPIO0 + base + 0x18) == mask
            q.write(GPIO0 + base + 0x28, mask)
            assert q.read(GPIO0 + base + 0x18) == 0
        for off, value in ((0x1010, 1), (0x1018, 2),
                           (0x10e0, 3), (0x1390, 4),
                           (0x13a0, 5), (0x1400, 6),
                           (0x1404, 7), (0x1500, 8),
                           (0x1508, 9), (0x150c, 10),
                           (0x1510, 11), (0x1520, 12)):
            q.write(GPIO0 + off, value)
            assert q.read(GPIO0 + off) == value
        print("G3C_GPIO_EVENT_AND_ANCILLARY_BATCH=PASS")

        # Before board's PINCM input routing is selected, external
        # nFAULT does not materialize in the digital input latch.
        assert not q.read(GPIO0 + DIN) & NFAULT
        q.write(PA22_PINCM, 0x00040081)
        assert q.read(GPIO0 + DIN) & NFAULT
        assert q.read(GPIO0 + 0x1314) == 0x00010000
        print("G3C_NFAULT_DEFAULT_HIGH_WHEN_CONNECTED=PASS")

        q.write(GPIO0 + 0x12c0, 0)
        q.write(GPIO0 + 0x1208, 0x00000101)
        q.write(GPIO0 + 0x12d0, 0x00000300)
        assert (q.read(GPIO0 + 0x1380) & 0x00000300) == 0x300
        assert q.read(GPIO1 + 0x1028) == 0
        print("PASS_G3C_ESC_SIM_GPIO_BOOTSTRAP")

    run(qemu, elf, True, False, functional)

    def asserted(q):
        q.write(GPIO0 + PWREN, 0x26000001)
        q.write(PA22_PINCM, 0x00040081)
        assert (q.read(GPIO0 + DIN) & NFAULT) == 0
        print("PASS_G3C_NFAULT_ASSERTED_LEVEL_INJECTION")

    run(qemu, elf, True, True, asserted)

    # Strict mode retains the old missing-MMIO rejection. Verify
    # QEMU reports a failed transaction, rather than trusting the
    # unspecified data value returned by a QTest error read.
    def strict(q):
        q.write(GPIO0 + PWREN, 0x26000001)
        q.read(GPIO0 + 0x1028)

    stderr = run(qemu, elf, False, False, strict)
    assert "G3_UNMODELED_GPIO0 read 0x400f1028" in stderr, stderr
    print("PASS_G3C_STRICT_MODE_REJECTS_UNMODELED_GPIO")


if __name__ == "__main__":
    main()
