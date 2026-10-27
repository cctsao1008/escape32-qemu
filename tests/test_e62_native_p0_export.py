#!/usr/bin/env python3
"""Source-unit-labelled rotor CSV and six-terminal mask export test."""
import csv, tempfile, sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p0_export import export_events


class P0CsvTests(unittest.TestCase):
    def test_rotor_and_switch_export_exact_units(self):
        events=[
            {"seq":1,"vns":1000,"kind":"SWITCH",
             "data":(0x21,1,15,0,0,0)},
            {"seq":2,"vns":2000,"kind":"ROTOR",
             "data":(12500,3142,1000,-2000,1000,250000)},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/"rotor.csv";b=Path(tmp)/"switch.csv"
            r=export_events(events,a,b)
            self.assertEqual(r,{"rotor_samples":1,"switch_changes":1})
            rows=list(csv.DictReader(a.open()))
            self.assertEqual(float(rows[0]["rpm"]),12.5)
            self.assertEqual(float(rows[0]["electrical_angle_unwrapped_rad"]),3.142)
            self.assertEqual(float(rows[0]["electromagnetic_torque_nm"]),.25)
            self.assertEqual(list(csv.DictReader(b.open()))[0]["six_pad_mask"],"0x21")


if __name__=="__main__":
    unittest.main(verbosity=2)
