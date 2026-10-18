#!/usr/bin/env python3
"""G1 test: read real Cortex-M33 CPU state via QEMU GDB RSP and step ELF.

No application binary rewriting, replacement startup, fake MMIO, or motor.
"""
import argparse
import os
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path

APP_BASE = 0x00006000
EXPECTED_SP = 0x20018000
EXPECTED_RESET_WORD = 0x0000DBFD


class RSP:
    def __init__(self, sock):
        self.sock = sock
        self.sock.settimeout(8)

    def byte(self):
        data = self.sock.recv(1)
        if not data:
            raise RuntimeError("GDB stub closed the connection")
        return data

    def command(self, payload):
        raw = payload.encode("ascii")
        checksum = sum(raw) & 255
        self.sock.sendall(b"$" + raw + f"#{checksum:02x}".encode())
        ack = self.byte()
        if ack != b"+":
            raise RuntimeError(f"Unexpected GDB RSP ACK: {ack!r}")
        start = self.byte()
        if start != b"$":
            raise RuntimeError(f"Unexpected GDB RSP reply start: {start!r}")
        packet = bytearray()
        while True:
            char = self.byte()
            if char == b"#":
                break
            packet.extend(char)
        sent = self.byte() + self.byte()
        if sent.decode("ascii").lower() != f"{sum(packet) & 255:02x}":
            self.sock.sendall(b"-")
            raise RuntimeError("Invalid RSP reply checksum")
        self.sock.sendall(b"+")
        result = packet.decode("ascii")
        if result.startswith("E"):
            raise RuntimeError(f"GDB RSP error for {payload}: {result}")
        return result

    def reg(self, n):
        result = self.command(f"p{n:x}")
        if len(result) != 8 or "x" in result:
            raise RuntimeError(f"Unavailable RSP register {n}: {result}")
        return struct.unpack("<I", bytes.fromhex(result))[0]

    def mem32(self, address):
        raw = self.command(f"m{address:x},4")
        if len(raw) != 8:
            raise RuntimeError(f"Cannot read CPU memory 0x{address:08x}: {raw}")
        return struct.unpack("<I", bytes.fromhex(raw))[0]


def wait_for_socket(path, process, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError(f"QEMU exited early: {process.stderr.read()}")
        try:
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.connect(path)
            return conn
        except (FileNotFoundError, ConnectionRefusedError):
            conn.close()
            time.sleep(0.05)
    raise TimeoutError(f"QEMU GDB socket did not appear: {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    args = parser.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for file in (qemu, elf):
        if not file.is_file():
            parser.error(f"Missing file: {file}")
    with tempfile.TemporaryDirectory(prefix="am13e-g1-") as tmp:
        socket_path = os.path.join(tmp, "gdb.sock")
        cmd = [
            str(qemu), "-M", "am13e23019", "-kernel", str(elf),
            "-display", "none", "-monitor", "none", "-serial", "none",
            "-S",
            "-chardev", f"socket,path={socket_path},server=on,wait=off,id=gdb0",
            "-gdb", "chardev:gdb0",
        ]
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, text=True)
        try:
            with wait_for_socket(socket_path, process) as conn:
                rsp = RSP(conn)
                halt = rsp.command("?")
                if not halt.startswith(("S", "T")):
                    raise RuntimeError(f"Unexpected CPU stop reply: {halt}")
                # QEMU 6.2 returns an empty reply to 'pN' until the
                # client requests target XML (gdbstub.c:handle_get_reg).
                # Fetch one XML byte: this enables XML-aware register reads
                # without needing a full XML parser or changing the guest.
                supported = rsp.command("qSupported:qXfer:features:read+")
                if "qXfer:features:read+" not in supported:
                    raise RuntimeError("QEMU GDB stub does not support target XML")
                xml_probe = rsp.command("qXfer:features:read:target.xml:0,1")
                if not xml_probe.startswith(("m<", "l<")):
                    raise RuntimeError(f"Unexpected target XML reply: {xml_probe!r}")
                sp, pc, xpsr = rsp.reg(13), rsp.reg(15), rsp.reg(25)
                vt = rsp.mem32(0xE000ED08)
                pfr1 = rsp.mem32(0xE000ED44)
                vec_sp, vec_pc = rsp.mem32(APP_BASE), rsp.mem32(APP_BASE + 4)
                print(f"APP_VECTOR SP=0x{vec_sp:08x} RESET=0x{vec_pc:08x}")
                print(f"G1_HANDOFF SP=0x{sp:08x} PC=0x{pc:08x} "
                      f"XPSR=0x{xpsr:08x} VTOR=0x{vt:08x} PFR1=0x{pfr1:08x}")
                assert (vec_sp, vec_pc) == (EXPECTED_SP, EXPECTED_RESET_WORD), "Rel17.3 image mismatch"
                assert sp == vec_sp and pc == (vec_pc & ~1), "CPU initial MSP/PC does not match original ELF"
                assert xpsr & 0x01000000, "Thumb state was not set"
                assert vt == APP_BASE, "Application VTOR was not relocated"
                assert (pfr1 & 0xF0) == 0, "M33 Security Extension still advertised"

                stop = rsp.command("s")
                if not stop.startswith(("S", "T")):
                    raise RuntimeError(f"CPU did not stop after stepping: {stop}")
                new_pc = rsp.reg(15)
                print(f"G1_STEP initial_PC=0x{pc:08x} next_PC=0x{new_pc:08x}")
                if new_pc == pc:
                    raise AssertionError("Original reset instruction did not advance PC")
                print("PASS_G1_APP_HANDOFF_AND_FIRST_INSTRUCTION")
                print("NOTE: PRIMASK=1 is applied by board reset callback; "
                      "not independently read by this GDB test.")
                print("NOTE: No SYSCTL/FRI, clock-ready or motor hardware modeled.")
        except Exception:
            if process.poll() is not None:
                print("QEMU stderr:", process.stderr.read())
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
