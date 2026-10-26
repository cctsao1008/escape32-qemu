"""Unit-only proof that U/V/W stimulus is Guest-route independent."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.functional_three_phase_bemf import (
    IndependentThreePhaseBemf, ThreePhaseConfig, load_three_phase_config,
)


class ThreePhaseIndependentStimulusTests(unittest.TestCase):
    def test_config_default_and_strict_unknown_mode(self):
        c = load_three_phase_config()
        self.assertEqual(c.electrical_hz, 100)
        self.assertEqual(c.center_code, 2048)
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / 'b.json'
            f.write_text(json.dumps({
                "schema":"e62.functional-bemf.v1",
                "mode":"GUEST_ROUTED",
                "electrical_hz":100,
                "initial_electrical_degrees":0,
                "center_code":2048,
                "amplitude_codes":128,
                "sample_wfi_interval":2}))
            with self.assertRaises(ValueError):
                load_three_phase_config(f)

    def test_exact_start_vector_and_120_degree_spacing(self):
        c = ThreePhaseConfig(100.0, -30.0, 2048, 128, 2)
        g = IndependentThreePhaseBemf(c)
        v = g.evaluate(guest_ns=0)
        self.assertEqual([x & 0xfff for x in v.analog_words],
                         [1984,1984,2176])
        self.assertEqual(v.electrical_degrees,330.0)
        self.assertEqual([x & 0x10000 for x in v.analog_words],
                         [0x10000]*3)

    def test_periodicity_without_guest_selected_code(self):
        c = ThreePhaseConfig(100.0, -30.0, 2048, 128, 2)
        g = IndependentThreePhaseBemf(c)
        self.assertEqual(g.evaluate(guest_ns=0).analog_words,
                         g.evaluate(guest_ns=10_000_000).analog_words)
        self.assertNotEqual(g.evaluate(guest_ns=0).analog_words,
                            g.evaluate(guest_ns=2_500_000).analog_words)

    def test_all_three_analog_ports_without_guest_writes(self):
        g = IndependentThreePhaseBemf(load_three_phase_config())
        base = 0x5ffe2000
        mem = {}
        for ms in range(24):
            sample = g.evaluate(guest_ns=ms*1_000_000)
            self.assertTrue(g.inject(sample, mem.__setitem__,
                                     mem.__getitem__, base))
        self.assertGreater(g.crossings_issued, 0)
        self.assertEqual(len(mem), 3)
        self.assertEqual(set(mem),{base,base+4,base+8})
        g.neutralize(mem.__setitem__,mem.__getitem__,base)
        self.assertEqual(tuple(mem[base+i*4] for i in range(3)),
                         (0x10000|2048,)*3)

    def test_backward_guest_clock_rejected(self):
        g = IndependentThreePhaseBemf(load_three_phase_config())
        mem = {}
        g.inject(g.evaluate(guest_ns=2_000_000), mem.__setitem__,
                 mem.__getitem__, 0x5ffe2000)
        with self.assertRaises(ValueError):
            g.inject(g.evaluate(guest_ns=1_000_000), mem.__setitem__,
                     mem.__getitem__, 0x5ffe2000)


if __name__ == "__main__":
    unittest.main()
