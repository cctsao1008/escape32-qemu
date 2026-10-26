"""Unit-only regression for source-oriented FunctionalSixPhaseAudit.

The examples are synthetic six-pad snapshots; they never prove real Guest.
"""
from types import SimpleNamespace
import unittest

from tools.functional_six_phase_audit import FunctionalSixPhaseAudit
from tools.native_closed_loop_audit import ORIGINAL_REL17_ROUTE


def image(step, *, good=True):
    hi, lo = ORIGINAL_REL17_ROUTE[step][1]
    values = [0] * 6
    values[2 * hi] = 650
    values[2 * lo + 1] = 6200
    if not good:
        values = [0, 0, 0, 0, 0, 0]
    return SimpleNamespace(
        native_pwm_valid=True, period_ticks=6251,
        gate_and_pads=True, pwm_powered=True,
        pwm_tbclk_enabled=True, physical_ost2=False, physical_ost3=False,
        six_high_ticks=tuple(values), acceptable_for_plant=True)


class SixPhaseFunctionalOracle(unittest.TestCase):
    def test_six_source_pairs_with_original_services_pass(self):
        a = FunctionalSixPhaseAudit()
        ns = 0
        a.observe(guest_time_ns=ns, guest_step=1,
                  guest_serviced=0, guest_captured=0)
        for service in range(1, 7):
            ns += 125_000
            step = (service % 6) + 1
            self.assertTrue(a.needs_pwm(step))
            a.observe(guest_time_ns=ns, guest_step=step,
                      guest_serviced=service, guest_captured=service,
                      pwm=image(step))
        result = a.report()
        self.assertEqual(result["status"],
                         "PASS_WFI_BRACKETED_SIX_PHASE_FUNCTIONAL_ONLY")
        self.assertEqual(result["settled_commutation_count"], 6)
        self.assertEqual(len(result["distinct_source_to_return_pairs"]), 6)
        self.assertFalse(result["exact_mcpwm_edge_timestamps_qualified"])

    def test_delayed_carrier_zero_publication_can_settle(self):
        a = FunctionalSixPhaseAudit()
        a.observe(guest_time_ns=0, guest_step=1,
                  guest_serviced=0, guest_captured=0)
        a.observe(guest_time_ns=125_000, guest_step=2,
                  guest_serviced=1, guest_captured=1, pwm=image(2,good=False))
        self.assertEqual(len(a.sectors),0)
        self.assertTrue(a.needs_pwm(2))
        a.observe(guest_time_ns=187_500, guest_step=2,
                  guest_serviced=1, guest_captured=1, pwm=image(2))
        self.assertEqual(len(a.sectors),1)
        self.assertEqual(a.sectors[0]["commutation_wfi_bracket_ns"],
                         [0,125_000])
        self.assertEqual(a.sectors[0]["pwm_settled_wfi_ns"],187_500)

    def test_actual_dshot300_complementary_pwm_sectors_settle(self):
        # Production-style QEMU high-tick data from Guest WFI captures.
        # The first snapshot after TIMG12 is still the prior source pair;
        # a later native carrier ZERO publishes the new complementary PWM.
        # Neither changes Guest source step or fabricates an IRQ.
        real = {
            1: (0, 0, 0, 4135, 115, 3988),
            2: (115, 3988, 0, 4135, 0, 0),
            3: (152, 3951, 0, 0, 0, 4135),
            4: (0, 0, 190, 3913, 0, 4135),
        }

        def observed(words):
            p = image(1)
            return SimpleNamespace(
                **dict(vars(p), period_ticks=4167,
                       six_high_ticks=words))

        a = FunctionalSixPhaseAudit()
        a.observe(guest_time_ns=0, guest_step=1,
                  guest_serviced=0, guest_captured=0, guest_throttle=120)
        for service, new_step in enumerate((2, 3, 4), start=1):
            old_step = new_step-1
            t = service * 250_000
            a.observe(guest_time_ns=t, guest_step=new_step,
                      guest_serviced=service, guest_captured=service,
                      guest_throttle=120, pwm=observed(real[old_step]))
            self.assertEqual(len(a.sectors), service-1)
            a.observe(guest_time_ns=t+62_500, guest_step=new_step,
                      guest_serviced=service, guest_captured=service,
                      guest_throttle=120, pwm=observed(real[new_step]))
            self.assertEqual(len(a.sectors), service)
        result = a.report()
        self.assertEqual(result["settled_commutation_count"], 3)
        self.assertEqual(result["failed_commutation_total"], 0)
        self.assertNotIn("PWM_DID_NOT_SETTLE_WITHIN_WFI_WINDOW", result["issues"])
        for sector in a.sectors:
            self.assertEqual(
                sector["measured_pwm_topology"],
                "COMPLEMENTARY_SOURCE_H_L_AND_SINK_L")
        # A partial three-sector bounded smoke is NOT an audit PASS.
        self.assertEqual(result["status"], "OPEN_OR_FAIL_SIX_PHASE_AUDIT")

    def test_failed_settle_preserves_real_six_pad_first_and_last(self):
        a = FunctionalSixPhaseAudit(settle_limit_ns=125_000)
        a.observe(guest_time_ns=0, guest_step=1,
                  guest_serviced=0, guest_captured=0, guest_throttle=150)
        a.observe(guest_time_ns=62_500, guest_step=2,
                  guest_serviced=1, guest_captured=1,
                  guest_throttle=150, pwm=image(1))
        a.observe(guest_time_ns=125_000, guest_step=2,
                  guest_serviced=1, guest_captured=1,
                  guest_throttle=150, pwm=image(1, good=False))
        a.observe(guest_time_ns=250_000, guest_step=2,
                  guest_serviced=1, guest_captured=1, guest_throttle=150)
        r = a.report()
        self.assertEqual(r["settled_commutation_count"], 0)
        self.assertEqual(r["failed_commutation_total"], 1)
        self.assertEqual(r["observed_guest_step_changes"], 1)
        f = r["first_failed_commutations"][0]
        self.assertEqual(f["expected_source_to_return"],
                         list(ORIGINAL_REL17_ROUTE[2][1]))
        self.assertEqual(f["pwm_observation_count"], 2)
        self.assertEqual(f["first_pwm_observation"]["six_high_ticks"],
                         list(image(1).six_high_ticks))
        self.assertEqual(f["last_pwm_observation"]["six_high_ticks"],
                         [0] * 6)
        self.assertIn("PWM_DID_NOT_SETTLE_WITHIN_WFI_WINDOW", r["issues"])
        self.assertEqual(r["status"], "OPEN_OR_FAIL_SIX_PHASE_AUDIT")

    def test_unobserved_pwm_is_diagnosed_not_a_sector(self):
        a = FunctionalSixPhaseAudit(settle_limit_ns=62_500)
        a.observe(guest_time_ns=0, guest_step=1,
                  guest_serviced=0, guest_captured=0)
        a.observe(guest_time_ns=62_500, guest_step=2,
                  guest_serviced=1, guest_captured=1)
        a.observe(guest_time_ns=187_500, guest_step=2,
                  guest_serviced=1, guest_captured=1)
        failed = a.report()["first_failed_commutations"][0]
        self.assertEqual(failed["pwm_observation_count"], 0)
        self.assertIsNone(failed["last_pwm_observation"])
        self.assertEqual(a.report()["settled_commutation_count"], 0)

    def test_missing_timg12_rejects_step_change(self):
        a = FunctionalSixPhaseAudit()
        a.observe(guest_time_ns=0,guest_step=1,
                  guest_serviced=0,guest_captured=0)
        a.observe(guest_time_ns=62500,guest_step=2,
                  guest_serviced=0,guest_captured=0,pwm=image(2))
        self.assertIn("UNSUPPORTED_GUEST_STEP_OR_TIMG12_SEQUENCE",
                      a.report()["issues"])

    def test_wrong_phase_is_not_accepted(self):
        a = FunctionalSixPhaseAudit(settle_limit_ns=125_000)
        a.observe(guest_time_ns=0,guest_step=1,
                  guest_serviced=0,guest_captured=0)
        a.observe(guest_time_ns=62500,guest_step=2,
                  guest_serviced=1,guest_captured=1,pwm=image(1))
        a.observe(guest_time_ns=250000,guest_step=2,
                  guest_serviced=1,guest_captured=1,pwm=image(1))
        self.assertIn("PWM_DID_NOT_SETTLE_WITHIN_WFI_WINDOW",
                      a.report()["issues"])

    def test_wrong_order_or_missed_step_fails_closed(self):
        a = FunctionalSixPhaseAudit()
        a.observe(guest_time_ns=0,guest_step=1,
                  guest_serviced=0,guest_captured=0)
        a.observe(guest_time_ns=62500,guest_step=3,
                  guest_serviced=1,guest_captured=1,pwm=image(3))
        self.assertIn("UNSUPPORTED_GUEST_STEP_OR_TIMG12_SEQUENCE",
                      a.report()["issues"])

    def test_original_guest_zero_step_is_legal_idle_without_fake_sector(self):
        a = FunctionalSixPhaseAudit()
        for n in range(6):
            a.observe(guest_time_ns=n * 62_500,
                      guest_step=0, guest_serviced=0,
                      guest_captured=0, guest_throttle=0)
        self.assertEqual(a.report()["observed_idle_wfi"], 6)
        self.assertEqual(a.report()["settled_commutation_count"], 0)
        self.assertEqual(a.report()["startup_seeds"], [])
        self.assertEqual(a.report()["status"], "OPEN_OR_FAIL_SIX_PHASE_AUDIT")
        self.assertNotIn("UNSUPPORTED_GUEST_STEP_OR_TIMG12_SEQUENCE",
                         a.report()["issues"])

    def test_original_idle_to_step_one_seeds_but_does_not_credit(self):
        a = FunctionalSixPhaseAudit()
        a.observe(guest_time_ns=0, guest_step=0, guest_serviced=0,
                  guest_captured=0, guest_throttle=0)
        self.assertFalse(a.needs_pwm(1))
        a.observe(guest_time_ns=62_500, guest_step=1, guest_serviced=0,
                  guest_captured=0, guest_throttle=30)
        self.assertEqual(a.report()["settled_commutation_count"], 0)
        self.assertEqual(a.report()["startup_seeds"][0]["initial_guest_step"], 1)
        self.assertEqual(a.report()["issues"],
                         ["NO_COMPLETE_POWERED_SIX_STEP_SEQUENCE"])
        a.observe(guest_time_ns=125_000, guest_step=2, guest_serviced=1,
                  guest_captured=1, guest_throttle=30, pwm=image(2))
        self.assertEqual(a.report()["settled_commutation_count"], 1)

    def test_original_idle_to_arbitrary_valid_source_step_is_seed_only(self):
        a = FunctionalSixPhaseAudit()
        a.observe(guest_time_ns=0, guest_step=0, guest_serviced=0,
                  guest_captured=0)
        a.observe(guest_time_ns=62_500, guest_step=4, guest_serviced=0,
                  guest_captured=0)
        self.assertEqual(a.report()["startup_seeds"][0]["initial_guest_step"], 4)
        self.assertNotIn("UNSUPPORTED_GUEST_STEP_OR_TIMG12_SEQUENCE",
                         a.report()["issues"])

    def test_unexpected_idle_under_throttle_cannot_be_silent(self):
        a = FunctionalSixPhaseAudit()
        a.observe(guest_time_ns=0, guest_step=1, guest_serviced=0,
                  guest_captured=0, guest_throttle=100)
        a.observe(guest_time_ns=62_500, guest_step=0, guest_serviced=0,
                  guest_captured=0, guest_throttle=100)
        self.assertIn("UNEXPECTED_GUEST_IDLE_WITH_NONZERO_THROTTLE",
                      a.report()["issues"])

    def test_not_an_exact_edge_or_rotor_qualification(self):
        a = FunctionalSixPhaseAudit()
        r = a.report()
        self.assertFalse(r["exact_mcpwm_edge_timestamps_qualified"])
        self.assertFalse(r["electrical_gate_driver_or_motor_qualified"])
        self.assertFalse(r["phase_independent_bemf_source_qualified"])


if __name__ == "__main__":
    unittest.main()
