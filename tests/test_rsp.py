#!/usr/bin/env python3
"""Unit tests for the GDB RSP reply classifier (no QEMU process needed)."""
import socket
import unittest

from g1_handoff import RSP, SDK_DELAY_LOOP, fast_forward_sdk_delay


def exchange(reply, command="qqemu.sstepbits"):
    payload = reply.encode("ascii")
    packet = b"+$" + payload + f"#{sum(payload) & 0xff:02x}".encode("ascii")
    client, server = socket.socketpair()
    try:
        server.sendall(packet)
        rsp = RSP(client)
        result = rsp.command(command)
        return result
    finally:
        client.close()
        server.close()


class ReplyClassification(unittest.TestCase):
    def test_qemu_sstepbits_reply_is_not_error(self):
        response = "ENABLE=1,NOIRQ=2,NOTIMER=4"
        self.assertEqual(exchange(response), response)

    def test_feature_reply_beginning_with_e_is_not_error(self):
        self.assertEqual(exchange("Enabled"), "Enabled")

    def test_two_digit_hex_error_is_rejected(self):
        for reply in ("E01", "E2a", "EFF"):
            with self.subTest(reply=reply):
                with self.assertRaisesRegex(RuntimeError, "GDB RSP error"):
                    exchange(reply)

    def test_other_replies_remain_unchanged(self):
        self.assertEqual(exchange("OK"), "OK")
        self.assertEqual(exchange("0x1"), "0x1")


class DelayRSPMock:
    def __init__(self, stop_pc=0x776a, nop=0xbf00, branch=0xd2fc):
        self.stop_pc = stop_pc
        self.ops = []
        self.code = {SDK_DELAY_LOOP[1]: nop, SDK_DELAY_LOOP[2]: branch}

    def mem16(self, address):
        return self.code[address]

    def reg(self, n):
        return {14: 0x776b, 15: self.stop_pc}[n]

    def command(self, op):
        self.ops.append(op)
        return "T05" if op == "c" else "OK"


class DelayBreakpoints(unittest.TestCase):
    def test_executed_to_caller(self):
        rsp = DelayRSPMock()
        self.assertEqual(fast_forward_sdk_delay(
            rsp, SDK_DELAY_LOOP[0], 0x7610), 0x776a)
        self.assertEqual(rsp.ops, [
            "Z0,776a,2", "Z0,7610,2", "c", "z0,7610,2", "z0,776a,2"
        ])

    def test_captures_hardfault_instead_of_hanging(self):
        rsp = DelayRSPMock(stop_pc=0x7610)
        self.assertEqual(fast_forward_sdk_delay(
            rsp, SDK_DELAY_LOOP[2], 0x7610), 0x7610)

    def test_fails_closed_when_elf_code_changes(self):
        rsp = DelayRSPMock(nop=0)
        with self.assertRaisesRegex(RuntimeError, "opcode mismatch"):
            fast_forward_sdk_delay(rsp, SDK_DELAY_LOOP[0], 0x7610)
        self.assertEqual(rsp.ops, [])

    def test_other_pc_is_untouched(self):
        rsp = DelayRSPMock()
        self.assertIsNone(fast_forward_sdk_delay(rsp, 0xc700, 0x7610))
        self.assertEqual(rsp.ops, [])


if __name__ == "__main__":
    unittest.main()
