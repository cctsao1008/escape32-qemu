import unittest
from tools.ci.verify_t02 import validate

class T02IndependentStrictGateTests(unittest.TestCase):
    def test_missing_stages_fails_closed(self):
        self.assertIn('requires_11_completed_stages',validate({'status':'PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL','dshot_frames_sent':110000}))
    def test_known_bad_crc_oracle_cannot_pass(self):
        self.assertIn('unresolved_oracle_issues',validate({'status':'PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL','issues':['bad_crc'],'dshot_frames_sent':110000}))
    def test_not_coerce_t01_into_t02(self):
        self.assertIn('expected_110000_frames',validate({'status':'PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL','dshot_frames_sent':11000}))
