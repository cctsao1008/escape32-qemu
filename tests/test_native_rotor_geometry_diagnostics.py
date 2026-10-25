import unittest
from tools.native_rotor_geometry_diagnostics import analyze_geometry, diagnose_rotor_model

class PinnedOriginalGuestRotorGeometry(unittest.TestCase):
    def test_all_six_source_steps_have_forward_aligned_torque(self):
        d=analyze_geometry()
        self.assertEqual(len(d['sectors']),6)
        self.assertTrue(d['aligned_all_six_positive_torque'])
        for x in d['sectors']:
            self.assertAlmostEqual(x['signed_torque_per_amp_kt'],1.5,places=9)
    def test_nonreciprocal_legacy_is_not_acceptable_electromagnetic_power(self):
        d=diagnose_rotor_model()
        self.assertAlmostEqual(d['legacy_ke_kt_power_ratio'],7.0,places=12)
        self.assertAlmostEqual(d['reciprocal_ke_kt_power_ratio'],1.0,places=12)
        self.assertTrue(d['legacy_forced_current_projection_at_each_commutation'])
        self.assertFalse(d['strict_native_rotor_direction_qualified'])
