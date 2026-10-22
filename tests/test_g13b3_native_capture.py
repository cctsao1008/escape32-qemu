#!/usr/bin/env python3
"""G13B3F: fail closed unless native counter, CAP1 and analog edge agree."""
import unittest
from dataclasses import replace
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_bemf_injection import NativeBemfStimulus
from tools.native_bemf_capture import prove_capture_from_native_samples


def stimuli(code_before=2048, code_after=2049, selected_code=5,
            phase=0):
    def sample(i, code):
        words = [0x10800] * 3
        words[phase] = 0x10000 | code
        return NativeBemfStimulus(
            sample_index=i, native_ecap_ticks=1000 + i*12500,
            motor_elapsed_ns=i*62500, selected_code=selected_code,
            selected_phase=phase, active_dac_code=2048,
            bemf_phase_v=(0., 0., 0.), sample_words=tuple(words),
            changed_from_neutral=True)
    return [sample(0, code_before), sample(1, code_after)]


class NativeCaptureAuditTests(unittest.TestCase):
    def test_rising_real_plant_cross_and_isr_and_cap(self):
        r = prove_capture_from_native_samples(
            stimuli(), cap1_before=0, cap1_after=13501,
            native_now=26000, guest_count_before=0, guest_count_after=1)
        self.assertEqual(r.comparator_edge, "RISING")
        self.assertEqual(r.crossing_input_code_after, 2049)

    def test_falling_native_selected_edge(self):
        r = prove_capture_from_native_samples(
            stimuli(2049, 2048, selected_code=1),
            cap1_before=0, cap1_after=13502, native_now=26000,
            guest_count_before=0, guest_count_after=1)
        self.assertEqual(r.comparator_edge, "FALLING")

    def test_cannot_fabricate_event_with_cap_alone_or_guest_count_alone(self):
        for cap, count in ((0, 1), (13501, 0)):
            with self.subTest(cap=cap, count=count):
                with self.assertRaises(AssertionError):
                    prove_capture_from_native_samples(
                        stimuli(), cap1_before=0, cap1_after=cap,
                        native_now=26000,
                        guest_count_before=0, guest_count_after=count)

    def test_reject_no_voltage_threshold_crossing(self):
        with self.assertRaisesRegex(AssertionError, "No phase"):
            prove_capture_from_native_samples(
                stimuli(2048, 2048), cap1_before=0, cap1_after=13501,
                native_now=26000, guest_count_before=0, guest_count_after=1)

    def test_reject_bad_capture_timing(self):
        for cap in (13499, 26001):
            with self.subTest(cap=cap):
                with self.assertRaisesRegex(AssertionError, "CAP1 not timestamped"):
                    prove_capture_from_native_samples(
                        stimuli(), cap1_before=0, cap1_after=cap,
                        native_now=26000,
                        guest_count_before=0, guest_count_after=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
