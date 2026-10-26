#!/usr/bin/env python3
"""Host-only negative controls for source-grounded G20 sector-edge audit."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_closed_loop_audit import ORIGINAL_REL17_ROUTE
from tools.native_rotor_phase_audit import (
    NativeRotorPhaseAudit, _selected_geometric_edge_deg,
    _source_field_target_deg,
)


class G20SectorEntryGeometricEdgeTests(unittest.TestCase):
    def test_pinned_original_selected_phase_and_polarity(self):
        # Exactly the original Rel17 source mapping, including Steps 3..6.
        expected = ((5, 0), (3, 60), (6, 120),
                    (1, 180), (7, 240), (2, 300))
        for step, (code, edge) in enumerate(expected, 1):
            with self.subTest(step=step):
                self.assertEqual(ORIGINAL_REL17_ROUTE[step][0], code)
                self.assertAlmostEqual(
                    _selected_geometric_edge_deg(step), edge, places=9)
                self.assertAlmostEqual(
                    _source_field_target_deg(step), edge, places=9)

    @staticmethod
    def make_audit(*, theta_at_sector_deg, rpm):
        audit = NativeRotorPhaseAudit(pole_pairs=21, significant_rpm=10)
        # Preceding observed Guest sector, not an invented CAP1.
        audit.observe(
            wfi_visit=1, integrated_ns=1_000_000,
            completed_sectors=0, guest_step=6,
            electrical_rad=math.radians(330),
            mechanical_rpm=160, phase_currents_a=(0., 0., 0.),
            torque_constant_nm_per_a=.0649, observed_pair=(2, 0))
        audit.observe(
            wfi_visit=2, integrated_ns=5_000_000,
            completed_sectors=1, guest_step=1,
            electrical_rad=math.radians(theta_at_sector_deg),
            mechanical_rpm=rpm, phase_currents_a=(10., -10., 0.),
            torque_constant_nm_per_a=.0649, observed_pair=(2, 1))
        return audit

    def test_g20_logged_step1_edge_already_behind_positive_rotor(self):
        audit = self.make_audit(theta_at_sector_deg=41.14641981779414,
                                rpm=165.0090685112506)
        result = audit.result()
        sector = result["observed_sector_checkpoints"][0]
        self.assertTrue(
            sector["selected_geometric_edge_already_behind_positive_rpm_at_wfi"])
        self.assertAlmostEqual(
            sector["rotor_past_selected_edge_signed_deg_at_wfi"],
            41.14641981779414, places=6)
        self.assertAlmostEqual(
            sector["forward_deg_to_next_same_polarity_geometric_edge_at_wfi"],
            318.85358018220586, places=6)
        self.assertEqual(
            result["observed_sector_selected_geometric_edge_behind_count"], 1)
        self.assertTrue(result["sector_entry_edge_screen_not_atomic_guest_service"])
        self.assertFalse(result["original_firmware_or_strict_gate_qualified"])

    def test_future_selected_edge_must_not_be_called_missed(self):
        audit = self.make_audit(theta_at_sector_deg=330., rpm=160.)
        sector = audit.result()["observed_sector_checkpoints"][0]
        self.assertFalse(
            sector["selected_geometric_edge_already_behind_positive_rpm_at_wfi"])
        self.assertAlmostEqual(
            sector["forward_deg_to_next_same_polarity_geometric_edge_at_wfi"],
            30., places=9)
        self.assertIsNone(
            audit.result()["first_sector_selected_geometric_edge_behind_positive_rpm"])

    def test_negative_or_zero_speed_is_not_positive_direction_edge_miss(self):
        for rpm in (-165., 0., 5.):
            with self.subTest(rpm=rpm):
                audit = self.make_audit(theta_at_sector_deg=41., rpm=rpm)
                self.assertFalse(
                    audit.result()["observed_sector_checkpoints"][0][
                        "selected_geometric_edge_already_behind_positive_rpm_at_wfi"])

    def test_first_reversal_retains_preceding_edge_miss_without_waiver(self):
        audit = self.make_audit(theta_at_sector_deg=41., rpm=165.)
        audit.observe(
            wfi_visit=3, integrated_ns=8_000_000,
            completed_sectors=1, guest_step=1,
            electrical_rad=math.radians(124.),
            mechanical_rpm=-31.6, phase_currents_a=(0., -60., 60.),
            torque_constant_nm_per_a=.0649, observed_pair=(2, 1))
        # Existing audit gates reversals only after 6 Guest sectors:
        # no fabricated reversal is permitted by a two-WFI toy scenario.
        self.assertIsNone(audit.result()["first_direction_reversal"])
        self.assertFalse(audit.result()["hardware_stability_qualified"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
