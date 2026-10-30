#!/usr/bin/env python3
"""E62 #5 manufacturer APC model sensitivity and source/fail-closed tests."""
import math, unittest, tempfile, json
from pathlib import Path
from tools.e62_apc24x12e_static import (load,static_torque,RPM,TORQUE_NM,MOTOR_ROTOR_J)
from tools.native_motor_model_profiles import (native_motor_parameters,
    APC_STUDY_PROFILES,DATASHEET_PROFILES,native_motor_model_metadata)

class APCProfileTest(unittest.TestCase):
    def test_maker_grid_exact_and_reverse_dissipation(self):
        self.assertEqual(static_torque(0),0)
        for rpm,tq in zip(RPM,TORQUE_NM):
            omega=rpm*math.pi/30
            self.assertAlmostEqual(static_torque(omega),tq,places=8)
            self.assertAlmostEqual(static_torque(-omega),-tq,places=8)
            self.assertAlmostEqual(static_torque(omega/2)*omega/2 > 0, True)
    def test_interior_interpolation_and_below_1000(self):
        self.assertAlmostEqual(static_torque(500*math.pi/30),0.033,places=8)
        self.assertAlmostEqual(static_torque(2500*math.pi/30),(0.494+1.085)/2,places=8)
    def test_fail_closed_out_of_source_range(self):
        for v in [float("nan"),float("inf"),-float("inf"),"x",True]:
            with self.assertRaises(ValueError): static_torque(v)
        with self.assertRaises(ValueError):
            static_torque(6001*math.pi/30)
    def test_exact_immutable_versioned_profile(self):
        d=load()
        self.assertEqual(d["effective_total_inertia_ratio_to_motor"],[1,2,5])
        for key,v in [("bus_voltage_v",24),
                      ("source_static_torque_nm",[0.1]*6),
                      ("propeller_inertia_measured",True),
                      ("motor_rearm_permitted_by_profile",True),
                      ("apc_airspeed_mph",20)]:
            changed=dict(d);changed[key]=v
            with tempfile.TemporaryDirectory() as td:
                path=Path(td)/"weakened.json"
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError): load(path)
    def test_historical_profiles_unchanged_new_profiles_distinct(self):
        for name in DATASHEET_PROFILES:
            p=native_motor_parameters(name)
            self.assertEqual(p.vbus_v,24)
            self.assertEqual(p.inertia_kg_m2,MOTOR_ROTOR_J)
            self.assertFalse(native_motor_model_metadata(name)["propeller_inertia_and_load_modeled"])
        for name,ratio in zip(APC_STUDY_PROFILES,[1,2,5]):
            p=native_motor_parameters(name)
            self.assertEqual(p.vbus_v,47)
            self.assertAlmostEqual(p.inertia_kg_m2,MOTOR_ROTOR_J*ratio)
            meta=native_motor_model_metadata(name)
            self.assertFalse(meta["propeller_inertia_measured"])
            self.assertTrue(meta["propeller_inertia_and_load_modeled"])
            self.assertEqual(meta["propeller_static_torque_model"],"APC_V0_MPH_1000_TO_6000RPM")
    def test_qemu_c_coefficients_match_independent_python_table(self):
        text=(Path(__file__).resolve().parents[1]/
              "machine/am13e_native_apc_propeller.inc").read_text()
        points=",".join(f"{v:.0f}." for v in RPM)
        torques=",".join(str(v) for v in TORQUE_NM)
        self.assertIn("{"+points+"}",text)
        self.assertIn("{"+torques+"}",text)
        self.assertIn("return NAN",text)
        self.assertIn("copysign",text)

if __name__=="__main__":
    unittest.main(verbosity=2)
