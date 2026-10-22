#!/usr/bin/env python3
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_power_path_qualification import qualify_cross_phase_bridge

class TestPowerPath(unittest.TestCase):
    def test_existing_pinned_guest_one_sink_cannot_claim_drive(self):
        s=qualify_cross_phase_bridge((0,0,0,6220,0,0),period_ticks=6251,gate_trip_qualified=True)
        self.assertFalse(s.qualifies_necessary_two_terminal_drive)
        self.assertEqual(s.reason,'NO_MEASURED_UPPER_MOSFET_SOURCE')
    def test_cross_phase_upper_source_lower_return(self):
        s=qualify_cross_phase_bridge((640,0,0,6220,0,0),period_ticks=6251,gate_trip_qualified=True)
        self.assertTrue(s.qualifies_necessary_two_terminal_drive)
        self.assertEqual(s.different_phase_pairs,((0,1),))
    def test_one_phase_only_is_not_cross_phase_drive(self):
        s=qualify_cross_phase_bridge((300,500,0,0,0,0),period_ticks=6251,gate_trip_qualified=True)
        self.assertFalse(s.qualifies_necessary_two_terminal_drive)
        self.assertEqual(s.reason,'NO_DISTINCT_PHASE_SOURCE_TO_RETURN')
    def test_physical_trip_overrides_even_correct_bridge(self):
        s=qualify_cross_phase_bridge((640,0,0,6220,0,0),period_ticks=6251,gate_trip_qualified=False)
        self.assertFalse(s.qualifies_necessary_two_terminal_drive)
        self.assertEqual(s.reason,'GATE_TRIP_NOT_QUALIFIED')
    def test_invalid_electrical_data_fails_closed(self):
        with self.assertRaises(ValueError):
            qualify_cross_phase_bridge((0,1),period_ticks=100,gate_trip_qualified=True)
        with self.assertRaises(ValueError):
            qualify_cross_phase_bridge((0,0,0,120,0,0),period_ticks=100,gate_trip_qualified=True)

if __name__=='__main__':unittest.main(verbosity=2)
