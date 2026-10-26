"""Host-only evidence: original DShot300 PWM six-pad high-tick patterns."""
import unittest

from tools.functional_pwm_phase_match import match_original_rel17_pwm_sector
from tools.native_closed_loop_audit import ORIGINAL_REL17_ROUTE


# Real six-pad QEMU PWM snapshots supplied by the 100-frame DShot300 run.
# Order: U_H, U_L, V_H, V_L, W_H, W_L; period=4167.
RUN_STEP2 = (115, 3988, 0, 4135, 0, 0)
RUN_STEP3 = (152, 3951, 0, 0, 0, 4135)
RUN_STEP4 = (0, 0, 190, 3913, 0, 4135)
RUN_STEP1 = (0, 0, 0, 4135, 115, 3988)


class FunctionalSixPadPatternTest(unittest.TestCase):
    def match(self, snapshot, step, period=4167):
        return match_original_rel17_pwm_sector(
            snapshot, period_ticks=period,
            expected_pair=ORIGINAL_REL17_ROUTE[step][1])

    def test_measured_complementary_step_1_through_4(self):
        for step, words in ((1, RUN_STEP1), (2, RUN_STEP2),
                            (3, RUN_STEP3), (4, RUN_STEP4)):
            with self.subTest(step=step):
                p = self.match(words, step)
                self.assertTrue(p.qualified, p)
                self.assertEqual(
                    p.mode, "COMPLEMENTARY_SOURCE_H_L_AND_SINK_L")
                self.assertEqual(p.sink_off_ticks, 32)
                self.assertEqual(p.source_high_low_off_ticks, 64)

    def test_dshot300_wrong_expected_pair_is_rejected(self):
        for step in (1, 3, 4, 5, 6):
            with self.subTest(step=step):
                self.assertFalse(self.match(RUN_STEP2, step).qualified)

    def test_valid_legacy_noncomplementary_is_not_disallowed(self):
        p = match_original_rel17_pwm_sector(
            (650, 0, 0, 6200, 0, 0), period_ticks=6251,
            expected_pair=(0, 1))
        self.assertTrue(p.qualified)
        self.assertEqual(p.mode, "NON_COMPLEMENTARY_SOURCE_H_AND_SINK_L")

    def test_unexpected_float_pad_fails(self):
        cases = [
            (115, 3988, 0, 4135, 0, 1),
            (115, 3988, 1, 4135, 0, 0),
            (115, 3988, 0, 4135, 1, 0),
            (115, 3988, 0, 4135, 0, 99),
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertFalse(self.match(case, 2).qualified)

    def test_bad_pwm_budget_or_sink_fails(self):
        cases = [
            (115, 4100, 0, 4135, 0, 0),  # source H+L overlap
            (115, 3920, 0, 4135, 0, 0),  # non-complementary budget
            (115, 3988, 0, 3600, 0, 0),  # sink not near full period
            (0, 3988, 0, 4135, 0, 0),    # source high absent
            (115, 3988, 0, 0, 0, 0),     # sink low absent
            (115, 4135, 0, 4135, 0, 0),  # sink-low and source-low equal
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertFalse(self.match(case, 2).qualified)

    def test_bad_inputs_fail_closed(self):
        for words, pair in [
            ((0, 1), (0, 1)),
            ((0, 0, 0, 0, 0, 0), (0, 0)),
            ((0, -1, 0, 0, 0, 0), (0, 1)),
            ((0, 4200, 0, 0, 0, 0), (0, 1)),
        ]:
            with self.subTest(words=words, pair=pair):
                with self.assertRaises(ValueError):
                    match_original_rel17_pwm_sector(
                        words, period_ticks=4167, expected_pair=pair)


if __name__ == "__main__":
    unittest.main()
