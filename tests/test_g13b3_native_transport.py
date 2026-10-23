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
from g11_exception_lifecycle import observer


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

    def test_contiguous_g11_observer_one_rsp_packet(self):
        client, server = socket.socketpair()
        errors = []
        words = tuple([0x47313101] + [0x20100000 + i for i in range(10)])
        payload = b"".join(v.to_bytes(4, "little") for v in words).hex().encode()

        def stub():
            try:
                raw = bytearray()
                while not raw.endswith(b"#"):
                    raw += server.recv(1)
                raw += server.recv(2)
                self.assertEqual(raw, b"$m5ffe3000,2c#" +
                                 checksum(b"m5ffe3000,2c"))
                server.sendall(b"+$" + payload + b"#" + checksum(payload))
                self.assertEqual(server.recv(1), b"+")
            except Exception as exc:
                errors.append(exc)
            finally:
                server.close()

        worker = threading.Thread(target=stub, daemon=True)
        worker.start()
        try:
            rsp = RSP(client)
            self.assertEqual(rsp.mem32_block(0x5ffe3000, 11), words)
            self.assertEqual(rsp.command_count, 1)
            self.assertEqual(rsp.recv_bytes, len(b"+$") + len(payload) + 3)
        finally:
            client.close()
            worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])


    @staticmethod
    def _rsp_words(*words):
        return b"".join(w.to_bytes(4, "little") for w in words).hex().encode()

    def _run_rsp_script(self, script, exercise):
        """Check exact read-only RSP sequence over a real socketpair."""
        client, server = socket.socketpair()
        errors = []

        def stub():
            try:
                for command, reply in script:
                    expected = b"$" + command + b"#" + checksum(command)
                    received = bytearray()
                    while len(received) < len(expected):
                        chunk = server.recv(len(expected) - len(received))
                        if not chunk:
                            raise RuntimeError("RSP request stream closed")
                        received.extend(chunk)
                    self.assertEqual(bytes(received), expected)
                    server.sendall(b"+$" + reply + b"#" + checksum(reply))
                    self.assertEqual(server.recv(1), b"+")
            except Exception as exc:
                errors.append(exc)
            finally:
                server.close()

        worker = threading.Thread(target=stub, daemon=True)
        worker.start()
        try:
            return exercise(RSP(client))
        finally:
            client.close()
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])

    def _g11_observer_script(self):
        # Native observer read; separate ICSR and independent CPU checks.
        native = (0x47313101, 1, 0, 0, 0, 0x20001000, 0x20002000,
                  0, 0xfffffff9, 0x0000679a, 0x01000000)
        return [
            (b"m5ffe3000,2c", self._rsp_words(*native)),
            (b"me000ed04,4", self._rsp_words(0)),
            (b"me000ed24,c", self._rsp_words(0x00070000, 0x00040000,
                                           0x00010000)),
            (b"p19", self._rsp_words(0x01000000)),
            (b"pd", self._rsp_words(0x20001000)),
            (b"pf", self._rsp_words(0x0000679a)),
        ]

    def test_g11_scb_triplet_one_packet_retains_all_cross_checks(self):
        def exercise(rsp):
            state = observer(rsp)
            return state, rsp.command_count

        state, commands = self._run_rsp_script(
            self._g11_observer_script(), exercise)
        self.assertEqual(commands, 6)  # 11 observer + ICSR + SCB3 + 3 regs
        self.assertEqual(state["icsr"], 0)
        self.assertEqual(state["shcsr"], 0x00070000)
        self.assertEqual(state["cfsr"], 0x00040000)
        self.assertEqual(state["hfsr"], 0x00010000)
        self.assertEqual(state["pc"], 0x0000679a)

    def test_g11_scb_short_response_is_fail_closed(self):
        script = self._g11_observer_script()[:3]
        script[2] = (script[2][0], self._rsp_words(0x00070000, 0x00040000))
        with self.assertRaisesRegex(RuntimeError, "Cannot read 3 Guest words"):
            self._run_rsp_script(script, observer)

    def test_g11_independent_core_mismatch_is_fail_closed(self):
        script = self._g11_observer_script()
        script[-1] = (b"pf", self._rsp_words(0x0000679c))
        with self.assertRaisesRegex(AssertionError, "G11 observer disagrees"):
            self._run_rsp_script(script, observer)

    def test_invalid_block_dimensions_fail_before_request(self):
        client, server = socket.socketpair()
        try:
            rsp = RSP(client)
            for address, count in ((0x5ffe3001, 11), (0x5ffe3000, 0),
                                   (0x5ffe3000, 33)):
                with self.subTest(address=hex(address), count=count):
                    with self.assertRaises(ValueError):
                        rsp.mem32_block(address, count)
        finally:
            client.close()
            server.close()

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
