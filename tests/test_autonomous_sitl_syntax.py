#!/usr/bin/env python3
"""Static parse regression for the G13B6 native runner and host entrypoints.

Previously unit tests imported autonomous_sitl_host but never parsed the
runtime module; an unmatched parenthesis at the first guest telemetry
sampling condition failed only *after* the physical Zero-DShot ARM path.
"""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AutonomousPythonSyntaxTests(unittest.TestCase):
    def test_runtime_entrypoints_parse_before_native_guest_launch(self):
        for relative in (
            'tools/native_arming.py',
            'tools/sitl_autonomous_transport.py',
            'tools/sitl_autonomous_evidence.py',
            'tools/sitl_stage_oracle.py',
            'tools/autonomous_sitl_runner.py',
            'tests/functional_dshot_sitl.py',
            'tools/autonomous_sitl_host.py',
            'tests/g13b4_functional_dshot_sitl.py',
        ):
            with self.subTest(relative=relative):
                file = ROOT / relative
                ast.parse(file.read_text(encoding='utf-8'),
                          filename=str(file))


if __name__ == '__main__':
    unittest.main()
