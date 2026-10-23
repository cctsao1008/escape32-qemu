#!/usr/bin/env python3
"""Real socketpair protocol guards for buffered GDB RSP and QTest transport.

No simulated Guest registers, fabricated CAP1, or altered native CI gates.
"""
import socket
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from g1_handoff import RSP
from g0_memory import QTest


def checksum(payload: bytes) -> bytes:
    return f"{sum(payload) & 0xff:02x}".encode("ascii")


class TestBufferedRSP(unittest.TestCase):
    def test_ack_reply_checksum_and_multi_command_preserve_stream(self):
        client, server = socket.socketpair()
        errors = []

        def stub():
            try:
                for command, reply in ((b"m1000,4", b"78563412"),
                                       (b"p0", b"efcdab90"),
                                       (b"qSupported", b"OK")):
                    raw = bytearray()
                    while not raw.endswith(b"#" + checksum(command)):
                        raw += server.recv(1)
                    self.assertEqual(bytes(raw), b"$" + command + b"#" +
                                     checksum(command))
                    # Coalesce ACK, reply and checksum into one write.
                    server.sendall(b"+$" + reply + b"#" + checksum(reply))
                    self.assertEqual(server.recv(1), b"+")
            except Exception as exc:
                errors.append(exc)
            finally:
                server.close()

        worker = threading.Thread(target=stub, daemon=True)
        worker.start()
        try:
            rsp = RSP(client)
            self.assertEqual(rsp.mem32(0x1000), 0x12345678)
            self.assertEqual(rsp.reg(0), 0x90abcdef)
            self.assertEqual(rsp.command("qSupported"), "OK")
            self.assertEqual(rsp.command_count, 3)
            self.assertGreater(rsp.recv_bytes, 0)
            self.assertLess(rsp.recv_calls, rsp.recv_bytes)
        finally:
            client.close()
            worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])

    def test_corrupt_checksum_is_rejected_with_negative_ack(self):
        client, server = socket.socketpair()
        errors = []

        def stub():
            try:
                raw = bytearray()
                while not raw.endswith(b"#") and len(raw) < 100:
                    raw += server.recv(1)
                server.recv(2)
                server.sendall(b"+$OK#00")
                self.assertEqual(server.recv(1), b"-")
            except Exception as exc:
                errors.append(exc)
            finally:
                server.close()

        t = threading.Thread(target=stub, daemon=True)
        t.start()
        try:
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                RSP(client).command("qSupported")
        finally:
            client.close()
            t.join(timeout=3)
        self.assertFalse(t.is_alive())
        self.assertEqual(errors, [])


class TestBufferedQTest(unittest.TestCase):
    def test_irq_notification_then_mmio_reply_in_same_buffer(self):
        client, server = socket.socketpair()
        errors = []

        def stub():
            try:
                stream = server.makefile("rb")
                self.assertEqual(stream.readline(), b"readl 0x00000100\n")
                server.sendall(b"IRQ raise 1\nOK 0x12345678\n")
                self.assertEqual(stream.readline(),
                                 b"writel 0x00000104 0x0000beef\n")
                server.sendall(b"IRQ lower 1\nOK\n")
                self.assertEqual(stream.readline(), b"readl 0x00000108\n")
                server.sendall(b"OK 0x0000002a\n")
            except Exception as exc:
                errors.append(exc)
            finally:
                server.close()

        t = threading.Thread(target=stub, daemon=True)
        t.start()
        try:
            qt = QTest(client)
            self.assertEqual(qt.read(0x100), 0x12345678)
            qt.write(0x104, 0xbeef)
            self.assertEqual(qt.read(0x108), 42)
            self.assertEqual((qt.command_count, qt.read_count,
                              qt.write_count), (3, 2, 1))
        finally:
            client.close()
            t.join(timeout=3)
        self.assertFalse(t.is_alive())
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
