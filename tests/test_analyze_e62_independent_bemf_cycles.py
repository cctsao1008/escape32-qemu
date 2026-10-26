#!/usr/bin/env python3
"""Host-only negative/positive controls for offline Guest cycle-slip metrics."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.analyze_e62_independent_bemf_cycles import analyze


def evidence(whole_extra_cycles=1, *, hz=900):
    dt=round((whole_extra_cycles+1/6)*1e9/hz)
    sectors=[]
    for i in range(8):
        sectors.append({
            "new_guest_step":i%6+1,
            "serviced_after":i+1,
            "commutation_wfi_bracket_ns":[1_100_000_000+i*dt-62_500,
                                           1_100_000_000+i*dt]})
    return {
        "bemf_input_mode":"INDEPENDENT_THREE_PHASE_FIXED_HZ",
        "independent_bemf_diagnostics":{
            "electrical_hz":hz,
            "phase_center_sign_changes":59000,
            "source_cap1_count_from_guest":8400},
        "six_phase_audit":{"sectors":sectors},
        "stages":[{"kind":"hold","start_ns":1_000_000_000,
                   "end_ns":11_000_000_000,
                   "original_timg12_service_delta":7714}],
        "status":"PASS_FUNCTIONAL_INDEPENDENT_THREE_PHASE_BEMF_ONLY"}


class OriginalGuestCycleSlipTests(unittest.TestCase):
    def test_one_extra_full_cycle_before_each_step(self):
        d=analyze(evidence(1))
        self.assertEqual(
            d["extra_full_electrical_cycles_before_next_guest_step_histogram"],
            {"1":7})
        self.assertAlmostEqual(d["median_degrees_per_guest_step"],420,delta=.05)
        self.assertFalse(d["physical_rotor_electrical_phase_lock_qualified"])

    def test_normal_sixty_degree_stride_no_extra_cycle(self):
        d=analyze(evidence(0))
        self.assertEqual(
            d["extra_full_electrical_cycles_before_next_guest_step_histogram"],
            {"0":7})
        self.assertAlmostEqual(d["median_degrees_per_guest_step"],60,delta=.05)

    def test_unrelated_stride_does_not_pass_as_cycle_slip(self):
        d=analyze(evidence(0,hz=500))
        # No claims about exact comparator capture time or physical rotor.
        self.assertEqual(d["hold_sectors_with_guest_wfi_time"],8)
        self.assertEqual(d["consecutive_sector_interval_count"],7)


if __name__=="__main__":
    unittest.main()
