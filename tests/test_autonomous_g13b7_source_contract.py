#!/usr/bin/env python3
"""G13B7 QEMU source integration preflight; does not replace native build."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


class G13B7SourceWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.autonomous=(ROOT/'machine/am13e_autonomous_sitl.inc').read_text()
        cls.machine=(ROOT/'machine/am13e23019.c').read_text()
        cls.feedback=(ROOT/'machine/am13e_motor_feedback.inc').read_text()

    def test_earliest_deadline_timer_coalescing_present(self):
        self.assertIn('timer_pending(a->bemf_timer)',self.autonomous)
        self.assertIn('timer_expire_time_ns(a->bemf_timer) <= due',
                      self.autonomous)
        self.assertIn('++a->route_coalesced',self.autonomous)
        self.assertIn('AM13E_AUTO_BEMF_CROSS_NS',self.autonomous)
        self.assertNotIn('AM13E_AUTO_BEMF_NS INT64_C(100000)',
                         self.autonomous)

    def test_native_capture_and_timer_hooks_after_acceptance(self):
        self.assertIn('am13e_auto_trace_cap1(f->machine);',self.feedback)
        self.assertLess(self.feedback.index('am13e_g10_flags(f, (uint16_t)(2U << event));'),
                        self.feedback.index('am13e_auto_trace_cap1(f->machine);'))
        self.assertIn('am13e_auto_trace_timg12_zero(t);',self.machine)
        self.assertIn('t->machine = s;',self.machine)

    def test_revised_abi_and_timing_are_readonly_observations(self):
        self.assertIn('case 0x88: *v = 4U',self.autonomous)
        for offset in ('0x9c','0xa0','0xa4','0xa8','0xac','0xfc'):
            self.assertIn('case '+offset,self.autonomous)
        self.assertIn('static void am13e_auto_trace_cap1',self.autonomous)
        self.assertIn('static void am13e_auto_trace_timg12_zero',
                      self.autonomous)

    def test_comparator_filter_retained_on_identical_pwm_dac(self):
        # Source wiring sanity; actual timer behavior must also pass
        # native QEMU integration below.
        self.assertIn('if (f->cmp[0x0eU / 2U] != shadow)',
                      self.feedback)
        self.assertIn('am13e_g10_stim_vector',self.feedback)
        self.assertIn('am13e_g10_stim_vector(f, words,',
                      self.autonomous)
        self.assertNotIn('am13e_g10_stim_write(f, i * 4U, words[i]',
                         self.autonomous)


if __name__=='__main__':
    unittest.main()
