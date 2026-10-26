"""External input config / DShot PA26 edge-plan unit tests.

Not an original Guest DShot300 receive PASS.
"""
import json
from pathlib import Path
import tempfile
import unittest

from tools.esc_input_protocol import (
    DEFAULT_CONFIG, DSHOT_TICKS, dshot_physical_edges, load_input_config)


class ConfigAndWireTests(unittest.TestCase):
    def test_checked_in_default_is_dshot300(self):
        config = load_input_config()
        self.assertEqual(config.protocol, "DSHOT300")
        self.assertEqual(config.frame_rate_hz, 1000)

    def test_all_dshot_variants_have_32_transitions(self):
        frame = 0xA35C
        for protocol, (period, hi1, hi0) in DSHOT_TICKS.items():
            with self.subTest(protocol=protocol):
                edges = dshot_physical_edges(frame, protocol)
                self.assertEqual(len(edges), 32)
                self.assertEqual(edges[0], (10000, 1))
                self.assertEqual([v for _, v in edges], [1, 0] * 16)
                for i in range(16):
                    high = hi1 if frame & (1 << (15-i)) else hi0
                    self.assertEqual(edges[2*i+1], (10*high, 0))
                    if i:
                        prior = hi1 if frame & (1 << (16-i)) else hi0
                        self.assertEqual(edges[2*i], (10*(period-prior), 1))

    def test_bad_configs_fail_closed(self):
        original = json.loads(DEFAULT_CONFIG.read_text())
        for protocol in ("DSHOT1200", "UNKNOWN", ""):
            with self.subTest(protocol=protocol), tempfile.TemporaryDirectory() as t:
                p = Path(t) / "bad.json"
                p.write_text(json.dumps(dict(original, protocol=protocol)))
                with self.assertRaises(ValueError):
                    load_input_config(p)
        with self.assertRaises(ValueError):
            dshot_physical_edges(0x1234, "PWM")

    def test_pwm_option_is_not_dshot(self):
        original = json.loads(DEFAULT_CONFIG.read_text())
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "pwm.json"
            p.write_text(json.dumps(dict(original, protocol="PWM")))
            self.assertEqual(load_input_config(p).protocol, "PWM")
            with self.assertRaises(ValueError):
                dshot_physical_edges(0x1234, "PWM")


if __name__ == "__main__":
    unittest.main()
