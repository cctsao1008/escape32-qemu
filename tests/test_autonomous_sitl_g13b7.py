#!/usr/bin/env python3
"""G13B7: timer/temporal ABI and sampled functional regression negative tests."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.functional_dshot_scenario import load_scenario
from tools.autonomous_sitl_host import (
    AUTO_ABI, AUTO_BASE, AUTO_MAGIC, REG, read_timing_evidence,
    sampled_stage_regression_gate,
)


class G13B7OracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / 'scenarios/e62-dshot-v1.json'
        cls.t01 = load_scenario(source,'T01')

    @staticmethod
    def fixture_samples():
        def row(ms,cmd,guest,crc,cap,t12,pwm):
            return dict(sim_elapsed_ms=ms,intended_command_dshot=cmd,
                sim_dshot_value=cmd,guest_throt_sample=guest,
                guest_valid_crc_feed_total=crc,guest_cap1_total=cap,
                guest_timg12_serviced_total=t12,
                pwm_observer_ready_sample=pwm,
                pwm_high_tick_ratios_sample=(
                    [0,0,0,1,.9,.1] if pwm else None),
                pwm_six_high_ticks_sample=(
                    [0,0,0,4167,3756,411] if pwm else None),
                pwm_period_ticks_sample=4167 if pwm else 0)
        return [
            row(0,0,0,1,0,0,False),
            row(211,426,379,200,161,144,True),
            row(414,786,739,399,348,330,True),
            row(617,1145,1098,594,535,517,True),
            row(820,1523,1476,790,721,703,True),
            row(1025,1847,1800,987,909,891,True),
            row(2200,1847,1800,2100,2100,2080,True),
            row(5800,1847,1800,5300,5100,5080,True),
            row(10802,1847,1800,10374,9887,9869,True),
        ]

    @staticmethod
    def fixture_checkpoints():
        return [
            dict(valid=True,complete=True,end_sent_cumulative=1000,
                 phase_polarity_mask=0x3f,phase_polarity_transitions=904),
            dict(valid=True,complete=True,end_sent_cumulative=11000,
                 phase_polarity_mask=0x3f,phase_polarity_transitions=9100),
        ]

    def test_historical_g13b6_t01_semantics_pass_sample_gate(self):
        rows,issues=sampled_stage_regression_gate(
            self.t01,self.fixture_checkpoints(),self.fixture_samples())
        self.assertEqual(issues,[])
        self.assertEqual([r['status'] for r in rows],
                         ['PASS_SAMPLED_STAGE_DIAGNOSTIC']*2)
        self.assertEqual(rows[1]['max_sampled_throttle_error'],0)

    def test_hold_throttle_regression_fails_without_aggregate_override(self):
        samples=self.fixture_samples()
        samples[-1]['guest_throt_sample']=1400
        _,issues=sampled_stage_regression_gate(
            self.t01,self.fixture_checkpoints(),samples)
        self.assertTrue(any('guest_throttle_out_of_tolerance' in x
                            for x in issues))

    def test_missing_stage_coverage_and_crc_stall_fail(self):
        samples=self.fixture_samples()
        samples[:]=[r for r in samples if r['sim_elapsed_ms']<4000]
        _,issues=sampled_stage_regression_gate(
            self.t01,self.fixture_checkpoints(),samples)
        self.assertTrue(any('insufficient_hold_coverage' in x for x in issues))
        samples=self.fixture_samples()
        for r in samples:
            r['guest_valid_crc_feed_total']=20
        _,issues=sampled_stage_regression_gate(
            self.t01,self.fixture_checkpoints(),samples)
        self.assertTrue(any('guest_crc_not_progressing' in x for x in issues))

    def test_low_crc_acceptance_ratio_fails_despite_positive_counter(self):
        samples=self.fixture_samples()
        for i,record in enumerate(samples):
            record['guest_valid_crc_feed_total']=i*2
        _,issues=sampled_stage_regression_gate(
            self.t01,self.fixture_checkpoints(),samples)
        self.assertTrue(any('sampled_crc_feed_ratio_below_90_percent' in x
                            for x in issues))

    def test_six_step_stuck_mask_fails_positive_hold(self):
        stages=self.fixture_checkpoints()
        stages[1]['phase_polarity_mask']=1
        _,issues=sampled_stage_regression_gate(
            self.t01,stages,self.fixture_samples())
        self.assertTrue(any('six_phase_polarity_states_not_observed' in x
                            for x in issues))

    def test_all_50pct_pwm_is_not_differential_drive(self):
        samples=self.fixture_samples()
        for r in samples:
            if r['pwm_observer_ready_sample']:
                r['pwm_six_high_ticks_sample']=[2083]*6
        _,issues=sampled_stage_regression_gate(
            self.t01,self.fixture_checkpoints(),samples)
        self.assertTrue(any('pwm_no_differential_phase_drive' in x
                            for x in issues))

    def test_invalid_overlapping_phase_pwm_fails(self):
        samples=self.fixture_samples()
        for r in samples:
            if r['pwm_observer_ready_sample']:
                r['pwm_six_high_ticks_sample']=[3000,3000,0,4167,3756,411]
        _,issues=sampled_stage_regression_gate(
            self.t01,self.fixture_checkpoints(),samples)
        self.assertTrue(any('pwm_phase_overlap' in x for x in issues))

    def test_incomplete_physical_checkpoint_fails(self):
        checkpoints=self.fixture_checkpoints()
        checkpoints[0]['complete']=False
        _,issues=sampled_stage_regression_gate(
            self.t01,checkpoints,self.fixture_samples())
        self.assertTrue(any('checkpoint_missing' in x for x in issues))

    def test_temporal_registers_and_64bit_sums(self):
        values={AUTO_BASE+REG['magic']:AUTO_MAGIC,
                AUTO_BASE+REG['abi_version']:AUTO_ABI,
                AUTO_BASE+REG['trace_cross_cap_pairs']:2,
                AUTO_BASE+REG['trace_cap_timg12_pairs']:1,
                AUTO_BASE+REG['trace_cross_cap_sum_lo']:30,
                AUTO_BASE+REG['trace_cross_cap_sum_hi']:0,
                AUTO_BASE+REG['trace_cap_timg12_sum_lo']:120,
                AUTO_BASE+REG['trace_cap_timg12_sum_hi']:0,
                AUTO_BASE+REG['trace_triplets']:1,
                AUTO_BASE+REG['feedback_timer_mods']:10,
                AUTO_BASE+REG['coalesced_route_changes']:4}
        metrics=read_timing_evidence(lambda addr:values.get(addr,0))
        self.assertEqual(metrics['trace_cross_cap_mean_ns'],15)
        self.assertEqual(metrics['trace_cap_timg12_mean_ns'],120)
        self.assertEqual(metrics['trace_triplets'],1)
        self.assertEqual(metrics['coalesced_route_changes'],4)
        self.assertIn('NOT_GUEST_ISR_PROOF',metrics['scope'])

    def test_g13b6_abi_cannot_masquerade_as_g13b7(self):
        values={AUTO_BASE+REG['magic']:AUTO_MAGIC,
                AUTO_BASE+REG['abi_version']:3}
        with self.assertRaisesRegex(RuntimeError,'ABI mismatch'):
            read_timing_evidence(lambda addr:values.get(addr,0))


if __name__=='__main__':
    unittest.main(verbosity=2)
