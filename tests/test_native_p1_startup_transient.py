#!/usr/bin/env python3
"""Native 50ms startup current/torque source-trace diagnostics; no P1 waiver."""
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p1_startup_transient import parse,measure


def source(seq,ns,kind,*values):
    data=values or (0,0,0,0,0,0)
    return (f"qemu-system-arm: E62_P0_EVENT seq={seq} vns={ns} "
            f"kind={kind} "+ " ".join(
                f"{k}={v}" for k,v in zip("abcdef",data))+"\n")


class P1StartupTransientTests(unittest.TestCase):
    def test_pre_first_timg12_reversal_witnessed(self):
        lines=[source(1,0,"DSHOT",1500,1,448,0,0,0),
               source(2,200000,"PWM_PAIR",8,24,15,0,0,0)]
        for i in range(10):
            rpm=200000 if i==0 else -80000 if i>1 else 110000
            torque=500000 if i==0 else -500000
            lines.append(source(i+3,(i+1)*1000000,"ROTOR",
                                rpm,0,25000,-25000,0,torque))
        lines.extend([source(13,10500000,"TIMG12",1,1,250000,0,0,0),
                      source(14,10600000,"PWM_PAIR",2,9,15,0,0,0)])
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"events.log"
            p.write_text("".join(lines))
            record=measure("direct20",parse(p))
        self.assertEqual(record["first_positive_dshot_value"],448)
        self.assertTrue(record["reverse_before_first_timg12"])
        self.assertTrue(record["reverse_before_second_pwm_sector"])
        self.assertEqual(record["max_abs_phase_current_a"],25.0)
        self.assertEqual(record["peak_negative_torque_nm"],-0.5)
        self.assertFalse(record["qualified"])

    def test_bad_source_sequence_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"wrong.log"
            p.write_text(source(1,1,"DSHOT",0,0,0,0,0,0)+
                         source(3,2,"DSHOT",1,0,0,0,0,0))
            with self.assertRaisesRegex(ValueError,"Non-monotone"):
                parse(p)


if __name__=="__main__":
    unittest.main(verbosity=2)
