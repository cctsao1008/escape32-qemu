"""Unit negative gates for Issue #5 timeout trace oracle. Not native QEMU evidence."""
import copy
import unittest
from tools.e62_issue5_timeout_oracle import audit

def trace():
    return {
        "schema": "e62.bemf-timeout-trace.v1",
        "source": "native_qemu",
        "firmware_sha256": "a" * 64,
        "qemu_sha": "b" * 40,
        "events": [
            {"t_ns": 0, "kind": "GATE_ENABLE", "enabled": True},
            {"t_ns": 1, "kind": "PWM_SIX", "mask": 3},
            {"t_ns": 1_000_000, "kind": "BEMF_TIMEOUT"},
            {"t_ns": 1_000_001, "kind": "PWM_SIX", "mask": 0},
            {"t_ns": 1_000_002, "kind": "GATE_ENABLE", "enabled": False},
            {"t_ns": 2_000_000, "kind": "PWM_SIX", "mask": 0},
            {"t_ns": 2_000_001, "kind": "GATE_ENABLE", "enabled": False},
            {"t_ns": 3_000_000, "kind": "PWM_SIX", "mask": 0},
            {"t_ns": 3_000_001, "kind": "GATE_ENABLE", "enabled": False},
        ]
    }


class TimeoutOracleNegative(unittest.TestCase):
    def test_structural_positive_fixture_is_not_hardware_qualification(self):
        self.assertTrue(audit(trace())["qualified"])

    def test_post_timeout_pwm_energized_fails(self):
        d = trace()
        d["events"][3]["mask"] = 3
        self.assertIn("ENERGIZED_PWM_AFTER_TIMEOUT", audit(d)["failures"])

    def test_gate_stays_enabled_fails(self):
        d = trace()
        d["events"][4]["enabled"] = True
        self.assertIn("GATE_ENABLED_AFTER_TIMEOUT", audit(d)["failures"])

    def test_stale_commutation_fails(self):
        d = trace()
        d["events"].insert(3, {"t_ns": 1_000_000, "kind": "TIMG12_COMMUTATION"})
        self.assertIn("STALE_COMMUTATION_AFTER_TIMEOUT", audit(d)["failures"])

    def test_missing_post_window_fails(self):
        d = trace()
        d["events"] = d["events"][:5]
        self.assertIn("POST_TIMEOUT_WINDOW_INCOMPLETE", audit(d)["failures"])

    def test_missing_pre_timeout_pwm_fails(self):
        d = trace()
        d["events"][1]["mask"] = 0
        self.assertIn("NO_PRIOR_ENERGIZED_PWM", audit(d)["failures"])

    def test_unordered_events_fail(self):
        d = trace()
        d["events"][2]["t_ns"] = 0
        self.assertIn("EVENT_INVALID_OR_UNORDERED", audit(d)["failures"])

    def test_unknown_source_or_missing_sha_fails(self):
        d = trace()
        d["source"] = "synthetic"
        d["qemu_sha"] = ""
        self.assertFalse(audit(d)["qualified"])

    def test_no_timeout_event_fails(self):
        d = trace()
        d["events"] = [e for e in d["events"] if e["kind"] != "BEMF_TIMEOUT"]
        self.assertIn("TIMEOUT_NOT_UNIQUE", audit(d)["failures"])

if __name__ == "__main__":
    unittest.main()
