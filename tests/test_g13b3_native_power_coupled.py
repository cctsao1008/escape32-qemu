#!/usr/bin/env python3
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_power_coupled_plant import NativePowerCoupledBLDC
from tools.virtual_bldc import MotorParameters

def motor():
    return NativePowerCoupledBLDC(MotorParameters(
        vbus_v=24,phase_resistance_ohm=.3,phase_inductance_h=.002,
        bemf_constant_v_per_rad_s=.02,torque_constant_nm_per_a=.02,
        inertia_kg_m2=1e-6,viscous_friction_nm_per_rad_s=.0001,
        load_torque_nm=0,pole_pairs=7))

class RealPowerPath(unittest.TestCase):
    def test_sink_only_never_bootstraps_fake_motor(self):
        m=motor()
        for _ in range(100):
            m.advance((0,0,0,6220/6251,0,0),.00005,gate_enabled=True)
        self.assertEqual(m.sample().mechanical_rpm,0)
        self.assertEqual(m.sample().bemf_phase_v,(0,0,0))
        self.assertFalse(m.ever_powered)
        self.assertEqual(m.energized_intervals,0)
    def test_distinct_source_and_return_accelerate(self):
        m=motor()
        for _ in range(100):
            m.advance((.3,0,0,.9,0,0),.00005,gate_enabled=True)
        self.assertGreater(m.energized_intervals,0)
        self.assertTrue(m.ever_powered)
        self.assertGreater(abs(m.sample().mechanical_rpm),0)
    def test_floating_third_phase_carries_no_fictitious_current(self):
        m=motor()
        m.advance((.3,0,0,.9,0,0),.00005,gate_enabled=True)
        self.assertAlmostEqual(m.iabc[2],0.0,places=12)
        self.assertAlmostEqual(m.iabc[0]+m.iabc[1],0.0,places=12)
    def test_two_terminal_fraction_is_high_pwm_not_sink_bias(self):
        m=motor()
        m.advance((.01,0,0,.99,0,0),.00005,gate_enabled=True)
        self.assertGreater(m.iabc[0],0)
        # Expected branch current from VBUS * .01 across two windings
        ideal=(24*.01/(2*.002))*.00005
        self.assertAlmostEqual(m.iabc[0],ideal,places=9)
    def test_nonqualified_multiple_sources_rejected(self):
        m=motor()
        with self.assertRaisesRegex(ValueError,"single-source"):
            m.advance((.1,0,.2,0,0,1),.00005,gate_enabled=True)

    def test_physical_rotor_pose_is_not_initial_kick_or_bemf(self):
        import math
        m=NativePowerCoupledBLDC(motor().p,initial_electrical_rad=-math.pi/6)
        self.assertAlmostEqual(m.sample().mechanical_rpm,0)
        self.assertEqual(m.sample().bemf_phase_v,(0.0,0.0,0.0))
        self.assertAlmostEqual(m.sample().electrical_rad,2*math.pi-math.pi/6)
        self.assertFalse(m.ever_powered)
    def test_invalid_rotor_pose_fail_closed(self):
        for v in (float("nan"),float("inf"),float("-inf")):
            with self.assertRaises(ValueError):
                NativePowerCoupledBLDC(motor().p,initial_electrical_rad=v)

    def test_gate_off_does_not_apply_bus(self):
        m=motor()
        for _ in range(100):
            m.advance((.3,0,0,.9,0,0),.00005,gate_enabled=False)
        self.assertEqual(m.sample().mechanical_rpm,0)
    def test_coast_does_not_gain_energy(self):
        m=motor()
        for _ in range(100):
            m.advance((.3,0,0,.9,0,0),.00005,gate_enabled=True)
        speed=abs(m.sample().mechanical_rpm)
        m.advance((0,0,0,.9,0,0),.00005,gate_enabled=True)
        self.assertLessEqual(abs(m.sample().mechanical_rpm),speed)
    def test_invalid_duty_rejected(self):
        m=motor()
        for d in [(0,0),(.3,0,0,0,0,float('nan'))]:
            with self.assertRaises(ValueError):
                m.advance(d,.00005,gate_enabled=True)

if __name__=='__main__':unittest.main(verbosity=2)
