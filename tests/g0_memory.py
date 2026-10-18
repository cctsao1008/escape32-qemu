#!/usr/bin/env python3
"""ELF/physical RAM tests. QTest does not execute guest instructions."""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path

class QTest:
    def __init__(self, sock):
        self.sock = sock
        self.stream = sock.makefile("rb", buffering=0)
        sock.settimeout(5)
    def cmd(self, command):
        self.sock.sendall((command + "\n").encode("ascii"))
        while True:
            line = self.stream.readline().decode("ascii").strip()
            if line.startswith("IRQ "):
                continue
            if not line.startswith("OK"):
                raise RuntimeError(f"QTest failure: {line!r}")
            return line.split()
    def read(self, address):
        return int(self.cmd(f"readl 0x{address:08x}")[1], 0)
    def write(self, address, value):
        self.cmd(f"writel 0x{address:08x} 0x{value:08x}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--elf', type=Path, required=True)
    args = parser.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for f in (qemu, elf):
        if not f.is_file():
            parser.error('file not found: ' + str(f))
    with tempfile.TemporaryDirectory(prefix='am13e-g0-') as tmp:
        path = os.path.join(tmp, 'qtest.sock')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(path)
            listener.listen(1)
            listener.settimeout(15)
            process = subprocess.Popen([
                str(qemu), '-machine', 'am13e23019,accel=qtest',
                '-kernel', str(elf), '-display', 'none', '-serial', 'none',
                '-monitor', 'none', '-qtest', f'unix:path={path}'
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                sock, _ = listener.accept()
                with sock:
                    qt = QTest(sock)
                    sp, reset = qt.read(0x6000), qt.read(0x6004)
                    print(f'APP_VECTOR SP=0x{sp:08x} RESET=0x{reset:08x}')
                    assert (sp, reset) == (0x20018000, 0x0000dbfd), 'Unexpected Rel17.3 ELF vectors'
                    for a, b, pattern in [
                        (0x20018000, 0x00c18000, 0x1234abcd),
                        (0x00c18004, 0x20018004, 0xdeadbeef),
                        (0x00c1fffc, 0x2001fffc, 0xa5a53c3c)
                    ]:
                        qt.write(a, pattern)
                        actual = qt.read(b)
                        print(f'Alias {a:#010x} -> {b:#010x} = {actual:#010x}')
                        assert actual == pattern, 'SRAM alias mismatch'
                    for addr in (0x20000000, 0x20010000):
                        qt.write(addr, 0x01020304)
                        assert qt.read(addr) == 0x01020304
                    print('PASS_G0_FLASH_AND_PHYSICAL_SRAM_ALIAS')
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

if __name__ == '__main__':
    main()
