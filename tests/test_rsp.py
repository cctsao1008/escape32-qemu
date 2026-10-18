#!/usr/bin/env python3
"""Unit tests for the GDB RSP reply classifier (no QEMU process needed)."""
import socket
import unittest

from g1_handoff import RSP


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


if __name__ == "__main__":
    unittest.main()
