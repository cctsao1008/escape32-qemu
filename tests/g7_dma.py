#!/usr/bin/env python3
"""G7: DMA0 CH2 real SRAM transport, 12-channel config and no phantom RX."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

DMA = 0x40020000
CTL, SRC, DST, SZ = (DMA+0x1220, DMA+0x1224,
                     DMA+0x1228, DMA+0x122c)
TRIGGER = DMA + 0x1118
IMASK, RIS, MIS, ICLR = (DMA+0x1028, DMA+0x1030,
                          DMA+0x1038, DMA+0x1048)
ENABLE_WORD = 0x00332272   # word/word, src/dst increment, half-size IRQ

def with_qtest(qemu, elf, sim, check):
    with tempfile.TemporaryDirectory(prefix="am13e-g7-") as directory:
        socket_path = os.path.join(directory, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(socket_path)
            server.listen(1)
            server.settimeout(15)
            proc = subprocess.Popen([
                str(qemu), "-machine", "am13e23019,accel=qtest,esc-sim=" +
                ("on" if sim else "off"), "-kernel", str(elf),
                "-display", "none", "-serial", "none", "-monitor", "none",
                "-qtest", f"unix:path={socket_path}"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                conn, _ = server.accept()
                with conn:
                    check(QTest(conn))
            finally:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                out = proc.stderr.read()
                proc.stderr.close()
    return out

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", required=True, type=Path)
    parser.add_argument("--elf", required=True, type=Path)
    args = parser.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for path in (qemu, elf):
        if not path.is_file():
            parser.error(f"File not found: {path}")

    def run(q):
        assert q.read(CTL) == 0
        assert q.read(SZ) == 0
        assert q.read(TRIGGER) == 0
        for ch in range(12):
            assert q.read(DMA + 0x1200 + 16*ch) == 0
            q.write(DMA + 0x1110 + 4*ch, ch + 1)
            assert q.read(DMA + 0x1110 + 4*ch) == ch + 1
        print("G7_DMA0_ALL_12_CHANNEL_CONFIG=PASS")

        # Actual Firmware uses trigger #34 from TIMG4 GEN_EVENT1.
        # Config does not fabricate any captured timestamp.
        q.write(CTL, 0)
        q.write(TRIGGER, 34)
        q.write(SRC, 0x40181810)  # TIMG4 CCP0
        q.write(DST, 0x20000300)
        q.write(SZ, 32)
        q.write(CTL, 0x00002202)  # enable, word/word, fixed source
        assert q.read(SZ) == 32
        assert q.read(DST) == 0x20000300
        q.cmd("clock_step 100000")
        assert q.read(SZ) == 32
        assert q.read(RIS) == 0
        print("G7_DMA0_TIMG4_TRIGGER34_NO_FAKE_EDGE=PASS")

        # In software trigger mode, a request must transfer ONE
        # actual word from guest SRAM and decrement the counter.
        q.write(CTL, 0)
        q.write(TRIGGER, 0)
        q.write(IMASK, (1 << 2) | (1 << 18) | (1 << 24))
        for i in range(4):
            q.write(0x20000040 + i*4, 0xA5240000 + i)
            q.write(0x20000340 + i*4, 0)
        q.write(SRC, 0x20000040)
        q.write(DST, 0x20000340)
        q.write(SZ, 4)
        q.write(CTL, ENABLE_WORD)
        assert q.read(SZ) == 4
        assert q.read(0x20000340) == 0  # no transfer upon config
        for i in range(4):
            q.write(CTL, q.read(CTL) | 1)
            assert q.read(0x20000340 + i*4) == 0xA5240000 + i
            assert q.read(SZ) == 3 - i
            assert q.read(SRC) == 0x20000044 + i*4
            assert q.read(DST) == 0x20000344 + i*4
            if i == 1:
                assert q.read(RIS) & (1 << 18), "Half-size early IRQ"
            if i < 3:
                assert not q.read(RIS) & (1 << 2), "premature DMA done"
        assert q.read(RIS) & (1 << 2)
        assert q.read(MIS) & (1 << 2)
        assert not q.read(CTL) & 2
        q.write(ICLR, (1 << 2) | (1 << 18))
        assert q.read(MIS) == 0
        print("G7_DMA0_CH2_REAL_SRAM_WORD_TRANSFER=PASS")
        print("G7_DMA0_CH2_COUNT_EARLY_AND_COMPLETE_IRQ=PASS")

        # Error requests are observable, never accepted as a
        # successful frame, and do not write to the receive buffer.
        q.write(SRC, 0x60000000)
        q.write(DST, 0x20000380)
        q.write(SZ, 1)
        q.write(CTL, 0x00002202)
        q.write(CTL, q.read(CTL) | 1)
        assert q.read(RIS) & (1 << 24)
        assert q.read(SZ) == 1
        assert not q.read(CTL) & 2
        print("PASS_G7_DMA0_CH2_FAULT_AND_NO_FAKE_CAPTURE")

    with_qtest(qemu, elf, True, run)

    def strict(q):
        q.read(CTL)
        q.write(CTL, 0x00002202)

    err = with_qtest(qemu, elf, False, strict)
    assert "G7_UNMODELED_DMA0 read 0x40021220" in err, err
    print("PASS_G7_STRICT_DMA0_FAIL_CLOSED")

if __name__ == "__main__":
    main()
