"""Negative fixtures for native timeout verdict. UNIT_ONLY, not QEMU proof."""
import unittest
from tools.e62_issue5_native_timeout_verdict import verdict


def fixture():
    pwm_off = dict(native_pwm_valid=True, gate_and_pads=False,
                   nonzero_phase_voltage_command=False)
    return {"g13b3i_original_no_bemf_timeout": {
        "simulator_feedback_injected": False,
        "pwm_before_timeout": dict(native_pwm_valid=True, gate_and_pads=True,
                                   nonzero_phase_voltage_command=True),
        "pwm_at_timeout": dict(pwm_off),
        "post_timeout_wfi_samples": [{"pwm": dict(pwm_off)} for _ in range(48)],
        "post_timeout_all_samples_six_off": True,
    }}


class NativeTimeoutVerdictTest(unittest.TestCase):
    def test_structural_fixture_only(self):
        self.assertTrue(verdict(fixture())["safe_off_observed"])

    def test_missing_history_fails_closed(self):
        d = fixture()
        d["g13b3i_original_no_bemf_timeout"]["post_timeout_wfi_samples"] = []
        self.assertIn("POST_TIMEOUT_HISTORY_INCOMPLETE", verdict(d)["failures"])

    def test_late_reenergization_is_rejected(self):
        d = fixture()
        d["g13b3i_original_no_bemf_timeout"]["post_timeout_wfi_samples"][47]["pwm"]["nonzero_phase_voltage_command"] = True
        self.assertIn("POST_TIMEOUT_ENERGIZED_PWM_RETAINED", verdict(d)["failures"])

    def test_gate_reenable_is_rejected(self):
        d = fixture()
        d["g13b3i_original_no_bemf_timeout"]["post_timeout_wfi_samples"][23]["pwm"]["gate_and_pads"] = True
        self.assertIn("POST_TIMEOUT_GATE_OR_PAD_CONNECTED", verdict(d)["failures"])

    def test_invalid_pwm_sample_is_rejected(self):
        d = fixture()
        d["g13b3i_original_no_bemf_timeout"]["post_timeout_wfi_samples"][5]["pwm"]["native_pwm_valid"] = False
        self.assertIn("POST_TIMEOUT_PWM_OBSERVER_INVALID", verdict(d)["failures"])

    def test_missing_native_report_fails(self):
        self.assertFalse(verdict({})["timeout_observed"])


if __name__ == "__main__":
    unittest.main()
