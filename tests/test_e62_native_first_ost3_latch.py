#!/usr/bin/env python3
"""Regression: E62 source-latched first physical OST3 cause is read-only."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class NativeFirstTripLatchContract(unittest.TestCase):
    def test_native_source_latches_trip_before_hardware_assertion(self):
        src=(ROOT/"machine/am13e_trip_safety.inc").read_text()
        start=src.index("if (s->native_motor.enabled &&")
        end=src.index("p->reg[0xb0U / 4U] |= new_ost;",start)
        code=src[start:end]
        self.assertIn("!(prior & AM13E_G13B2_TZ_OST3)",code)
        self.assertIn("m->first_ost3_oc_valid",code)
        self.assertIn("am13e_g13b2_cmp_ready(s, i)",code)
        self.assertIn("am13e_g13b2_cmp_trip(s, i)",code)
        self.assertIn("m->first_ost3_cpu_pc",code)
        self.assertNotIn("p->reg[0xb0U / 4U] =",code)
        self.assertNotIn("qemu_set_irq",code)

    def test_plant_instrumentation_is_read_only_and_reset_at_boot(self):
        src=(ROOT/"machine/am13e_native_motor_plant.inc").read_text()
        self.assertIn("#define AM13E_NATIVE_MOTOR_SIZE 0xb4U",src)
        self.assertIn("case 0xa0:",src)
        self.assertIn("configured_initial_electrical_mdeg",
                      (ROOT/"tests/e62_autonomous_native_motor_probe.py").read_text())
        self.assertIn("m->first_ost3_seen = false;",src)
        self.assertIn("case 0x4c: *v=m->first_ost3_oc_valid;",src)
        self.assertIn("case 0x80: *v=m->first_ost3_ipsr;",src)
        self.assertIn("return MEMTX_ERROR;",src.split(
            "static MemTxResult am13e_native_motor_write",1)[1])

    def test_probe_preserves_original_guest_and_motor_strict_gate(self):
        src=(ROOT/"tests/e62_autonomous_native_motor_probe.py").read_text()
        self.assertIn('"first_ost3_oc_codes"',src)
        self.assertIn('"first_ost3_dac_codes"',src)
        self.assertIn("No source-clocked PWM motor BEMF coupling:",src)
        self.assertIn('"used_guest_wfi_or_gdb": False',src)


if __name__=="__main__":
    unittest.main(verbosity=2)
