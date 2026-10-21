#!/usr/bin/env python3
"""Unit-level regressions for G13B original-ELF candidate-WFI discovery.

These tests validate *harness control flow only*. QEMU native execution
and electrically authorized motor operation have separate acceptance.
"""
import unittest
from unittest.mock import patch

from g13b_native_wfi import wait_for_native_main_wfi


def state(pc, ipsr=0, primask=0, cfsr=0, hfsr=0):
    return {
        "pc": pc, "ipsr": ipsr, "primask": primask,
        "cfsr": cfsr, "hfsr": hfsr, "icsr": 0,
    }


class NativeWFICandidates(unittest.TestCase):
    def exercise(self, events, max_slices=4):
        # An event consists of a QEMU RSP stop packet, whether the
        # stop was bounded Ctrl-C, and an observed (read-only) CPU state.
        iterator = iter(events)

        def simulated_continue(_rsp, _slice_ms):
            result, cpu = next(iterator)
            self.latest_cpu = cpu
            return result

        with patch("g13b_native_wfi.continue_bounded",
                   side_effect=simulated_continue), patch(
                   "g13b_native_wfi.observer",
                   side_effect=lambda _rsp: self.latest_cpu):
            return wait_for_native_main_wfi(
                object(), (0x676a, 0x68f8), 0x7000, 50,
                max_slices, stage="SELFTEST")

    def test_second_original_wfi_is_not_skipped(self):
        self.assertEqual(
            self.exercise([(("S05", False), state(0x68f8))]), 0x68f8)

    def test_bounded_pause_is_not_wfi_but_resumes(self):
        events = [(("T02", True), state(0x6510, ipsr=15)),
                  (("S05", False), state(0x68f8))]
        self.assertEqual(self.exercise(events), 0x68f8)

    def test_timeout_is_never_success(self):
        events = [(("T02", True), state(0x6510))] * 2
        with self.assertRaisesRegex(AssertionError, "no real native main WFI"):
            self.exercise(events, max_slices=2)

    def test_fault_never_accepted_as_wfi(self):
        with self.assertRaisesRegex(AssertionError, "genuine native CPU fault"):
            self.exercise([(("S05", False), state(0x7000, ipsr=3,
                                                   cfsr=0x40000))])

    def test_only_unmasked_thread_can_enter_wfi(self):
        with self.assertRaisesRegex(AssertionError, "not in unmasked"):
            self.exercise([(("S05", False), state(0x676a, ipsr=15))])

    def test_other_breakpoint_not_accepted(self):
        with self.assertRaisesRegex(AssertionError, "non-WFI"):
            self.exercise([(("S05", False), state(0x6500))])


if __name__ == "__main__":
    unittest.main(verbosity=2)
