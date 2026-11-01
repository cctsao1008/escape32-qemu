"""UNIT tests for archived QEMU CAP1/TIMG12 source-event classifier."""
import unittest
from tools.e62_issue5_cap1_timer_audit import parse, classify


def event(i, vns, kind):
    return f"qemu: E62_P0_EVENT seq={i} vns={vns} kind={kind} a=0 b=2 c=0 d=0 e=0 f=0"


class Cap1TimerAuditTests(unittest.TestCase):
    def test_ack_and_read_without_timer_is_not_claimed_as_timer_failure(self):
        log = "\n".join([
            event(1, 1_000, "CAP1"), event(2, 1_036, "CAP1_ACK"),
            event(3, 1_140, "ECAP1_CAP1_READ"),
            event(4, 5_000, "CAP1"), event(5, 5_036, "CAP1_ACK"),
            event(6, 5_140, "ECAP1_CAP1_READ"),
            event(7, 5_980, "T12_LOAD"), event(8, 6_160, "T12_START"),
        ])
        actual = classify(parse(log), 0, 10_000)
        self.assertEqual(actual[0]["classification"],
                         "READ_WITHOUT_TIMER_PROGRAMMING")
        self.assertEqual(actual[1]["classification"],
                         "READ_AND_TIMER_PROGRAMMED")

    def test_unread_cap1_does_not_claim_firmware_rejection(self):
        log = "\n".join([event(1, 1000, "CAP1"), event(2, 2000, "CAP1")])
        actual = classify(parse(log), 0, 3000)
        self.assertEqual(actual[0]["classification"], "NO_CAPTURE_ACK_OR_READ")

    def test_load_without_start_fails_as_incomplete(self):
        log = "\n".join([event(1, 1000, "CAP1"),
                         event(2, 1010, "CAP1_ACK"),
                         event(3, 1020, "ECAP1_CAP1_READ"),
                         event(4, 1100, "T12_LOAD")])
        self.assertEqual(classify(parse(log), 0, 2000)[0]["classification"],
                         "INCOMPLETE_TIMER_PROGRAMMING")

    def test_unordered_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "disordered"):
            parse("\n".join([event(1, 2000, "CAP1"),
                              event(2, 1000, "CAP1_ACK")]))


if __name__ == "__main__":
    unittest.main()
