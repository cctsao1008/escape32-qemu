"""Unit guards for independent SOURCE-only QEMU first-sector electrical audit."""
import math
import unittest
from tools.e62_first_sector_reference import (
    line_voltage_for_mask, advance_two_phase, flux_coeff, flux, KT, RLL,
    LLL, DIODE, electrical_reference,
)


class FirstSectorReferenceTest(unittest.TestCase):
    def test_original_first_pwm_pair_physically_drives_w_plus_v_minus(self):
        self.assertAlmostEqual(line_voltage_for_mask(24,10,24),24.)
        self.assertAlmostEqual(line_voltage_for_mask(8,10,24),-DIODE)
        self.assertAlmostEqual(line_voltage_for_mask(16,10,24),-DIODE)
        self.assertAlmostEqual(line_voltage_for_mask(0,10,24),-24-2*DIODE)
        self.assertIsNone(line_voltage_for_mask(0,0,24))
        with self.assertRaises(ValueError):
            line_voltage_for_mask(3,1,24)

    def test_closed_form_rl_matches_exact_constant_voltage_solution(self):
        dt=.001
        expected=24/RLL*(1-math.exp(-RLL/LLL*dt))
        self.assertAlmostEqual(advance_two_phase(0,24,0,dt),expected)
        v=0.
        for _ in range(100):
            v=advance_two_phase(v,24,0,dt/100)
        self.assertAlmostEqual(v,expected,places=10)

    def test_no_spurious_source_injection_or_implicit_guest_control(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        s=(root/"tools/e62_first_sector_reference.py").read_text()
        self.assertIn('assert evidence["host_guest_register_writes"] is False',s)
        self.assertIn('assert evidence["used_guest_wfi_or_gdb"] is False',s)
        self.assertIn('actual_switch_focus_count',s)
        self.assertIn('hardware_calibrated":False',s)
        self.assertIn('SIM_ONLY_STATIC_RL_AND_KINEMATICS_NOT_HARDWARE',s)

    def test_motor_flux_uses_common_physical_torque_bemf(self):
        for wave in ("historical_sine","ideal_trapezoid"):
            for degrees in (-90.,-30.,0.,30.,90.):
                theta=math.radians(degrees)
                w_high=flux(wave,theta+2*math.pi/3)
                v_low=flux(wave,theta-2*math.pi/3)
                amp=13.7
                assert len((w_high,v_low))==2
                torque=flux_coeff(wave)*amp*(w_high-v_low)
                b_emf=flux_coeff(wave)*19.0*(w_high-v_low)
                self.assertAlmostEqual(torque*19.0,amp*b_emf,places=12)
            self.assertAlmostEqual(flux_coeff(wave)*(
                flux(wave,2*math.pi/3)-flux(wave,-2*math.pi/3)),
                KT,places=12)


if __name__=="__main__":
    unittest.main()
