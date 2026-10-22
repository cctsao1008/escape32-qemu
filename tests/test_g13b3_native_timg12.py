#!/usr/bin/env python3
"""Read-only native timer snapshot: never fabricate an IRQ."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_timg12_observer import (
    TIMG12_BASE, observe_native_timg12)


class NativeTimg12ObserverTests(unittest.TestCase):
    def make(self, ctrctl=0x20000021, count=25, load=99):
        self.calls = []
        reg = {
            0x1008:8,0x1000:0,0x1108:1,0x110c:0,
            0x1028:1,0x1030:0,0x1038:0,
            0x1804:ctrctl,0x1808:load,0x1800:count,
        }
        def read(addr):
            self.calls.append(addr)
            if addr-TIMG12_BASE not in reg:
                raise AssertionError("Read outside genuine TIMG12 register")
            return reg[addr-TIMG12_BASE]
        return read

    def test_counter_irq_snapshot_has_only_hardware_reads(self):
        s = observe_native_timg12(self.make(), native_ecap_ticks=0xaabbccdd)
        self.assertTrue(s.counter_enabled)
        self.assertEqual(s.remaining_ticks,75)
        self.assertEqual(s.irq_mask,1)
        self.assertEqual(len(self.calls),10)
        self.assertEqual({a-TIMG12_BASE for a in self.calls},
                         {0x1008,0x1000,0x1108,0x110c,
                          0x1028,0x1030,0x1038,
                          0x1804,0x1808,0x1800})

    def test_countdown_remaining_and_stopped_timer(self):
        s = observe_native_timg12(
            self.make(ctrctl=1,count=22),native_ecap_ticks=123)
        self.assertEqual(s.remaining_ticks,23)
        s = observe_native_timg12(
            self.make(ctrctl=0,count=22),native_ecap_ticks=456)
        self.assertFalse(s.counter_enabled)
        self.assertEqual(s.remaining_ticks,0)

    def test_bad_counter_or_unbounded_timestamp_fail_closed(self):
        with self.assertRaisesRegex(AssertionError, "exceeds reload"):
            observe_native_timg12(self.make(count=100),
                                  native_ecap_ticks=1)
        for t in (-1,0x100000000):
            with self.assertRaises(ValueError):
                observe_native_timg12(self.make(), native_ecap_ticks=t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
