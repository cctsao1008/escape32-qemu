#!/usr/bin/env python3
"""G16 synthetic host unit tests; not original-Guest or real motor proof."""
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_motor_model_profiles import (
    PROFILES, DATASHEET_PROFILES, native_motor_parameters,
    native_motor_model_metadata)
from tools.native_sim_cfg_flash import ABI_EXPECTED
from tools.sim_motor_cfg import (
    TELEM_POLES_CFG_OFFSET, build_profile_cfg_flash,
    require_matching_profile_cfg)
from tools.current_continuous_bldc import CurrentContinuousBLDC, LegTopology
from tools.virtual_bldc_feedback import AnalogFrontend


class MotorProfileTests(unittest.TestCase):
    def test_historical_profiles_exactly_preserved(self):
        old = native_motor_parameters("legacy")
        rec = native_motor_parameters("reciprocal")
        self.assertEqual((old.pole_pairs, old.phase_resistance_ohm,
                          old.phase_inductance_h, old.inertia_kg_m2,
                          old.bemf_constant_v_per_rad_s,
                          old.torque_constant_nm_per_a),
                         (7, 0.3, 0.002, 1e-6, 0.02, 0.02))
        self.assertEqual(rec.torque_constant_nm_per_a, 0.14)
        self.assertEqual(rec.bemf_constant_v_per_rad_s, 0.02)
        self.assertEqual(len(PROFILES), 4)

    def test_ecx87_published_values_and_explicit_assumptions(self):
        specs = {
            "ecx87-kv147": (147.0, .0649, .106/2, .000048/2),
            "ecx87-kv210": (210.0, .0454, .0566/2, .0000175/2),
        }
        for profile, (kv, kt, r, l) in specs.items():
            with self.subTest(profile=profile):
                p = native_motor_parameters(profile)
                meta = native_motor_model_metadata(profile)
                self.assertEqual(p.pole_pairs, 21)
                self.assertEqual(p.inertia_kg_m2, .00013)
                self.assertAlmostEqual(p.phase_resistance_ohm, r)
                self.assertAlmostEqual(p.phase_inductance_h, l)
                self.assertAlmostEqual(p.torque_constant_nm_per_a,
                                       kt/math.sqrt(3.0))
                self.assertAlmostEqual(p.bemf_constant_v_per_rad_s*21,
                                       kt/math.sqrt(3.0))
                self.assertAlmostEqual(
                    math.sqrt(3.0)*p.torque_constant_nm_per_a, kt)
                self.assertEqual(meta["published_kv_rpm_per_v"], kv)
                self.assertAlmostEqual(
                    meta["phase_peak_flux_constant_v_s_per_rad"],
                    kt/math.sqrt(3.0))
                self.assertLess(
                    abs(kt*2*math.pi*kv/60.0-1.0), 0.01)
                self.assertEqual(meta["motor_poles_for_escape32_telem_poles"],42)
                self.assertFalse(meta["propeller_inertia_and_load_modeled"])
                self.assertFalse(meta["physical_motor_calibrated"])
                self.assertIn("ASSUMED", meta["ke_convention_assumption"])
                self.assertEqual(meta["electromagnetic_power_ratio_pe_over_pm"], 1.0)

    def test_model_feeds_comparator_bemf_from_rotor_rpm(self):
        f = AnalogFrontend(3.3, 1.65, 0.02)
        for profile in DATASHEET_PROFILES:
            p = native_motor_parameters(profile)
            m = CurrentContinuousBLDC(p, initial_electrical_rad=.4)
            sample = m.sample()
            self.assertEqual(sample.mechanical_rpm, 0)
            self.assertEqual(f.words(sample), (0x10800,)*3)
            m.omega_mech_rad_s = 100.0
            sample = m.sample(gate_enabled=True)
            self.assertAlmostEqual(sample.bemf_phase_v[0],
                                   p.torque_constant_nm_per_a*100*math.sin(.4))
            self.assertNotEqual(f.words(sample), (0x10800,)*3)
            m.set_switches(LegTopology(("Z", "L", "H")))
            for _ in range(10):
                m.advance(1e-6)
            self.assertGreater(m.integrated_intervals, 0)

    def test_only_telemetry_poles_are_provisioned_in_sim_flash(self):
        source = bytearray(b"\xff"*332)
        source[:4] = b"\xea\x32\x11\x03"
        source[TELEM_POLES_CFG_OFFSET] = 14
        for _, (offset, expected) in ABI_EXPECTED.items():
            source[offset] = expected
        with patch("tools.sim_motor_cfg.extract_cfgdata",
                   return_value=bytes(source)):
            for profile in DATASHEET_PROFILES:
                image, meta = build_profile_cfg_flash(b"fixture", profile)
                self.assertEqual(len(image), 336)
                self.assertEqual(image[TELEM_POLES_CFG_OFFSET], 42)
                differing = [i for i in range(len(source))
                             if image[i] != source[i]]
                self.assertEqual(differing, [TELEM_POLES_CFG_OFFSET])
                self.assertEqual(meta["changed_cfg_fields"], ["telem_poles"])
                self.assertEqual(meta["telem_poles_before"], 14)
                self.assertEqual(meta["telem_poles_after"], 42)
                require_matching_profile_cfg(b"fixture", image, profile)
                corrupt = bytearray(image)
                corrupt[33] ^= 1  # source DUTY_RATE is not a motor setting
                with self.assertRaisesRegex(ValueError, "does not exactly match"):
                    require_matching_profile_cfg(b"fixture", corrupt, profile)
            with self.assertRaisesRegex(ValueError, "Only documented ECX87"):
                build_profile_cfg_flash(b"fixture", "legacy")

    def test_actual_unchanged_rel17_3_elf_profile_image(self):
        # This repository's immutable original ELF, not a fabricated symbol
        # map, proves that the original Cfg ABI offset really exists.
        elf = (Path(__file__).resolve().parents[1] /
               "baseline/e62-g13b3/firmware/AM13E-rev17.3.elf")
        original = elf.read_bytes()
        for profile in DATASHEET_PROFILES:
            with self.subTest(profile=profile):
                image, meta = build_profile_cfg_flash(original, profile)
                self.assertEqual(image[TELEM_POLES_CFG_OFFSET], 42)
                self.assertEqual(meta["telem_poles_after"], 42)
                self.assertTrue(meta["original_guest_elf_unchanged"])
                self.assertEqual(meta["scope"],
                                 "SIM_ONLY_PREBOOT_FLASH_CFG_NOT_ORIGINAL_GUEST_UART_CLI")
                require_matching_profile_cfg(original, image, profile)

    def test_reject_unknown_profile(self):
        with self.assertRaisesRegex(ValueError, "Unknown explicit"):
            native_motor_parameters("motor-from-nowhere")


if __name__ == "__main__":
    unittest.main()
