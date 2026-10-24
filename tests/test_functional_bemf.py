#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.functional_bemf import FunctionalBemf, FunctionalBemfError

class BemfTests(unittest.TestCase):
    def test_falling_crosses_only_after_time(self):
        b = FunctionalBemf(crossing_delay_ns=700_000)
        kw = dict(guest_step=1, selected_code=5, selected_phase=0,
                  expected_edge_falling=False, dac_code=2048)
        a=b.evaluate(guest_ns=10000,**kw)
        mid=b.evaluate(guest_ns=709999,**kw)
        after=b.evaluate(guest_ns=710000,**kw)
        self.assertFalse(a.crossing_issued)
        self.assertEqual(a.analog_words,mid.analog_words)
        self.assertTrue(after.crossing_issued)
        self.assertNotEqual(after.analog_words,mid.analog_words)
        self.assertEqual((a.analog_words[0]&4095,after.analog_words[0]&4095),
                         (1920,2176))
        nxt=b.evaluate(guest_ns=750000,guest_step=2,selected_code=3,
                  selected_phase=2,expected_edge_falling=True,dac_code=2048)
        self.assertFalse(nxt.crossing_issued)
        self.assertEqual(nxt.analog_words[2]&4095,2176)
        retry=b.evaluate(guest_ns=2_110_000, guest_step=1,selected_code=5,
                    selected_phase=0,expected_edge_falling=False,dac_code=2048)
        self.assertFalse(retry.crossing_issued)  # reset on a new observed step

    def test_external_port_only_and_readback(self):
        b=FunctionalBemf()
        v=b.evaluate(guest_ns=0,guest_step=1,selected_code=5,
                     selected_phase=0,expected_edge_falling=False,dac_code=2048)
        mem={}
        def read(a): return mem[a]
        def write(a,v): mem[a]=v
        self.assertTrue(b.inject(v,write,read,0x5ffe2000))
        self.assertFalse(b.inject(v,write,read,0x5ffe2000))
        self.assertEqual(sorted(mem),[0x5ffe2000,0x5ffe2004,0x5ffe2008])
        self.assertEqual(b.crossings_issued,0)

    def test_invalid_route_fails(self):
        b=FunctionalBemf()
        with self.assertRaises(FunctionalBemfError):
            b.evaluate(guest_ns=0,guest_step=0,selected_code=5,
                    selected_phase=0,expected_edge_falling=True,dac_code=2048)

if __name__ == '__main__':
    unittest.main(verbosity=2)
