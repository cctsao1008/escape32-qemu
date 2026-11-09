"""UNIT checks of orchestration/identity, not executed motor scenarios."""
import tempfile
import unittest
from pathlib import Path
from tools.e62_exact_cmpss_suite import plan,check_inputs,ELF_SHA


class ExactSuiteTests(unittest.TestCase):
    def test_exact_historical_case_plan(self):
        rows=plan();self.assertEqual(len(rows),14)
        self.assertEqual(sum(r['stress']=='off' for r in rows),6)
        self.assertEqual({r['stress'] for r in rows},{'off','0:16','16:0','-16:0','16:20'})
        self.assertEqual(len({(r['case'],r['stress']) for r in rows}),14)

    def test_source_equivalent_binary_is_not_an_exact_substitute(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'filtered.elf';p.write_bytes(b'UNIT-not-the-candidate')
            with self.assertRaisesRegex(ValueError,'no substitute'):check_inputs(p,p)
        self.assertEqual(ELF_SHA,'5b90b200429333cef82b982b7a7f845f31fb885c7ea63fc7e783c75232fac8d1')


if __name__=='__main__':unittest.main()
