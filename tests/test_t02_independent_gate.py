import unittest
from tools.ci.verify_t02 import validate

class T02IndependentStrictGateTests(unittest.TestCase):
    def test_missing_stages_fails_closed(self):
        self.assertIn('requires_11_completed_stages',validate({'status':'PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL','dshot_frames_sent':110000}))
    def test_known_bad_crc_oracle_cannot_pass(self):
        self.assertIn('unresolved_oracle_issues',validate({'status':'PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL','issues':['bad_crc'],'dshot_frames_sent':110000}))
    def test_not_coerce_t01_into_t02(self):
        self.assertIn('expected_110000_frames',validate({'status':'PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL','dshot_frames_sent':11000}))


from types import SimpleNamespace
from tools.sitl_stage_oracle import sampled_stage_regression_gate

class StageTransitionOracleTests(unittest.TestCase):
    @staticmethod
    def fixture_commands():
        stages = [SimpleNamespace(index=i,kind='hold',to_pct=p,from_pct=p,
            start_ns=i*10_000_000_000,end_ns=(i+1)*10_000_000_000)
            for i,p in enumerate((0,10))]
        cps = [dict(valid=True,complete=True,end_sent_cumulative=10000,
                    phase_polarity_mask=0,phase_polarity_transitions=0),
               dict(valid=True,complete=True,end_sent_cumulative=20000,
                    phase_polarity_mask=63,phase_polarity_transitions=300)]
        samples=[]
        for idx,start in ((0,0),(1,10000)):
            for offset in (200,500,900,2500,4900,8000,9500):
                ms=start+offset
                command=0 if idx==0 else 248
                guest=0 if idx==0 or offset<500 else 201
                powered=idx==1 and offset>=500
                samples.append(dict(sim_elapsed_ms=ms,intended_command_dshot=command,
                    sim_dshot_value=command,guest_throt_sample=guest,
                    guest_valid_crc_feed_total=int(ms*.96),
                    guest_cap1_total=int(ms*.86),
                    guest_timg12_serviced_total=int(ms*.85),
                    pwm_observer_ready_sample=powered,
                    pwm_six_high_ticks_sample=[400,0,0,2500,0,2200] if powered else [0]*6,
                    pwm_period_ticks_sample=3000))
        return SimpleNamespace(stages=stages),cps,samples

    def test_transition_stale_initial_sample_can_settle(self):
        s,c,r=self.fixture_commands()
        report,issues=sampled_stage_regression_gate(s,c,r)
        self.assertEqual(issues,[])
        self.assertEqual(report[1]['transition_grace_ms'],500)

    def test_transition_stale_after_grace_fails(self):
        s,c,r=self.fixture_commands()
        for sample in r:
            if sample['sim_elapsed_ms']>10700:
                sample['guest_throt_sample']=0
        _,issues=sampled_stage_regression_gate(s,c,r)
        self.assertTrue(any('guest_throttle_out_of_tolerance' in x for x in issues))

    def test_neutral_powered_differential_phase_fails(self):
        s,c,r=self.fixture_commands()
        for sample in r:
            if sample['sim_elapsed_ms']<10000:
                sample['pwm_observer_ready_sample']=True
                sample['pwm_six_high_ticks_sample']=[500,0,0,1000,0,500]
        _,issues=sampled_stage_regression_gate(s,c,r)
        self.assertTrue(any('neutral_stage_powered_pwm' in x for x in issues))
