import unittest
from types import SimpleNamespace
from tools.sitl_sequence_audit import sampled_original_sequence_audit

class SampledSourceRouteTests(unittest.TestCase):
    @staticmethod
    def scenario():
        return SimpleNamespace(stages=[
            SimpleNamespace(index=0,kind='hold',start_ns=0,end_ns=1_000_000_000)])
    def test_source_exact_route_table_is_not_guessed(self):
        d=sampled_original_sequence_audit(self.scenario(),[
            dict(sim_elapsed_ms=10,guest_step_sample=1,
                 guest_selected_code_sample=5,guest_cap1_total=1,
                 guest_timg12_serviced_total=1),
            dict(sim_elapsed_ms=20,guest_step_sample=2,
                 guest_selected_code_sample=3,guest_cap1_total=2,
                 guest_timg12_serviced_total=2),
        ])
        self.assertEqual(d['pinned_source_sequence'],[5,3,6,1,7,2])
        self.assertEqual(d['stages'][0]['source_code_matches'],2)
        self.assertIn('OPEN_',d['status'])
    def test_mismatched_sample_not_called_sequence_pass(self):
        d=sampled_original_sequence_audit(self.scenario(),[
            dict(sim_elapsed_ms=50,guest_step_sample=1,
                 guest_selected_code_sample=7,guest_cap1_total=1,
                 guest_timg12_serviced_total=1),
        ])
        self.assertEqual(d['stages'][0]['source_code_mismatches'],1)
        self.assertIn('NOT_PROVEN',d['status'])
