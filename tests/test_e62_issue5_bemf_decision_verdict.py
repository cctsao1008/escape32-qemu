"""Source-only negative fixtures; NOT evidence of a real 47V Guest run."""
import unittest
from tools.e62_issue5_bemf_decision_verdict import audit


def fixture(decision="REJECTED_EARLY", capture=300, ival=1000, delay=0):
    return {"issue5_bemf_first_history": {
        "seq_after": 1, "first_history_capped": False,
        "entries": [{"seq": 0, "tick": 24000, "capture_us": capture,
                     "ival_before": ival, "delay_us": delay,
                     "decision": decision}]}}


class DecisionVerdictTests(unittest.TestCase):
    def test_valid_rejection(self):
        self.assertEqual(audit(fixture())["counts"]["REJECTED_EARLY"], 1)

    def test_false_rejection_rejected(self):
        with self.assertRaisesRegex(ValueError, "CONTRADICTS"):
            audit(fixture(capture=700))

    def test_accept_must_schedule_delay(self):
        with self.assertRaisesRegex(ValueError, "ACCEPTED_RECORD"):
            audit(fixture(decision="ACCEPTED", delay=0))

    def test_missing_history_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "MISSING"):
            audit({})

    def test_no_alignment_claim(self):
        self.assertEqual(audit(fixture())["target_cap1_1508_832ms_classification"],
                         "NOT_PROVEN_BY_UNALIGNED_HISTORY")

    def test_sequence_gap_rejected(self):
        doc=fixture()
        doc["issue5_bemf_first_history"]["entries"][0]["seq"]=2
        with self.assertRaisesRegex(ValueError,"SEQUENCE"):
            audit(doc)


if __name__=="__main__":
    unittest.main()
