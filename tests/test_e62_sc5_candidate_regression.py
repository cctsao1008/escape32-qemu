from pathlib import Path
import tempfile
import unittest
from tools.e62_sc5_candidate_regression import PLAN,CANDIDATE,guard
class RegressionTests(unittest.TestCase):
    def test_fourteen_distinct_cases_separate_from_issue3_identity(self):
        self.assertEqual(len(PLAN),14);self.assertEqual(len(set(PLAN)),14)
        self.assertEqual(sum(s is None for _,s in PLAN),6)
        self.assertNotEqual(CANDIDATE,'5b90b200429333cef82b982b7a7f845f31fb885c7ea63fc7e783c75232fac8d1')
    def test_substitute_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'wrong';p.write_bytes(b'not the candidate')
            with self.assertRaises(ValueError):guard(p,p)
if __name__=='__main__':unittest.main()
