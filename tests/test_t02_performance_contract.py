import unittest
from tools.ci.benchmark_autonomous import analyze

class RepeatabilityBenchmarkTests(unittest.TestCase):
    def test_same_host_statistics_only(self):
        d=analyze([dict(wall_elapsed_s=35,returncode=0,status='PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL'),
                   dict(wall_elapsed_s=37,returncode=0,status='PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL')])
        self.assertEqual(d['median_wall_s'],36)
        self.assertIn('OPEN_',d['speedup_against_g13b6'])
    def test_functional_failure_never_becomes_fastest_benchmark(self):
        d=analyze([dict(wall_elapsed_s=1,returncode=1,status='FAIL_AUTONOMOUS_ORACLE')])
        self.assertTrue(d['status'].startswith('FAIL'))
