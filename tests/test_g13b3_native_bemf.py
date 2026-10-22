#!/usr/bin/env python3
"""G13B3C native BEMF comparator/ECAP readiness read-only negative tests."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.native_bemf_qualification import (
    CMPSS0, ECAP1, SYS_HP_MUX, ECAP_POWER,
    observe_original_bemf_route, audit_native_bemf_arm_nm
)


def fixture(code=5):
    phase = (code & 3)-1
    return {
        ECAP_POWER: 0x410,
        SYS_HP_MUX: phase,
        CMPSS0: 0x8008,
        CMPSS0 + 0x0c: 2048 << 16,
        ECAP1 + 0x24: 45,
        ECAP1 + 0x28: (0x10 << 16) | 0x100 |
                        (0 if code & 4 else 1),
        ECAP1 + 0x2c: 2
    }


class NativeBemfRoute(unittest.TestCase):
    def test_native_reversed_polarity_phase_u(self):
        f = fixture(5)
        e = observe_original_bemf_route(
            lambda addr: f.get(addr, 0),
            selected_code=5, native_armed=True)
        self.assertTrue(e.channel_ready_for_voltage_samples)
        self.assertEqual(e.selected_phase, 0)
        self.assertFalse(e.expected_edge_falling)
        self.assertEqual(e.active_dac_code, 2048)

    def test_native_standard_falling_phase_v(self):
        f = fixture(2)
        e = observe_original_bemf_route(
            lambda addr: f.get(addr, 0), selected_code=2, native_armed=True)
        self.assertTrue(e.channel_ready_for_voltage_samples)
        self.assertEqual(e.selected_phase, 1)
        self.assertTrue(e.expected_edge_falling)

    def test_reject_missing_guest_arming(self):
        f = fixture(5)
        e = observe_original_bemf_route(
            lambda addr: f.get(addr, 0), selected_code=5, native_armed=False)
        self.assertFalse(e.channel_ready_for_voltage_samples)
        self.assertIn("not armed", e.reason)

    def test_reject_route_dac_filter_and_capture_gates(self):
        conditions = (
            (SYS_HP_MUX, 2),
            (CMPSS0, 0),
            (CMPSS0 + 0x0c, 0),
            (ECAP1 + 0x24, 0),
            (ECAP1 + 0x28, 0),
            (ECAP1 + 0x2c, 0),
            (ECAP_POWER, 0),
        )
        for addr, value in conditions:
            with self.subTest(address=hex(addr)):
                f = fixture(5)
                f[addr] = value
                self.assertFalse(observe_original_bemf_route(
                    lambda a: f.get(a, 0),
                    selected_code=5, native_armed=True
                ).channel_ready_for_voltage_samples)

    def test_reject_wrong_ecap_event_polarity(self):
        f = fixture(5)
        f[ECAP1 + 0x28] |= 1
        self.assertIn("polarity", observe_original_bemf_route(
            lambda a: f.get(a, 0),
            selected_code=5, native_armed=True).reason)

    def test_idle_zero_not_phantom_bemf(self):
        f = fixture(5)
        e = observe_original_bemf_route(
            lambda a: f.get(a, 0),
            selected_code=0, native_armed=False)
        self.assertIsNone(e.selected_phase)
        self.assertFalse(e.channel_ready_for_voltage_samples)

    def test_compiler_suffixed_static_arm_unique(self):
        s = "200003f0 00000004 b armed.0 /tmp/motor_bemf.c:63\n"
        self.assertEqual(audit_native_bemf_arm_nm(s).address, 0x200003f0)

    def test_unscoped_duplicates_fail_closed(self):
        s = ("200003f0 00000004 b armed\n"
             "20000410 00000004 b armed.0\n")
        a = audit_native_bemf_arm_nm(s)
        self.assertIsNone(a.address)
        self.assertIn("ambiguous", a.reason)

    def test_scoped_ambiguity_resolved_by_original_c_file(self):
        s = ("200003f0 00000004 b armed /tmp/other.c:10\n"
             "20000410 00000004 b armed.1 /tmp/motor_bemf.c:63\n")
        self.assertEqual(audit_native_bemf_arm_nm(s).address, 0x20000410)

    def test_invalid_or_wrong_source_does_not_resolve(self):
        for s in ("", "200003f0 00000008 b armed\n",
                  "200003f0 00000004 b unarmed\n",
                  "200003f0 00000004 b armed /tmp/other.c:5\n",
                  "000003f0 00000004 b armed /tmp/motor_bemf.c:63\n"):
            with self.subTest(symbol_table=s):
                self.assertIsNone(audit_native_bemf_arm_nm(s).address)


if __name__ == "__main__":
    unittest.main(verbosity=2)
