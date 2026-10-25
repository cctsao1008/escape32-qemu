import unittest
from tools.ci.verify_t02 import validate

class T02IndependentStrictGateTests(unittest.TestCase):
    def test_missing_stages_fails_closed(self):
        self.assertIn('requires_11_completed_stages',validate({'status':'PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL','dshot_frames_sent':110000}))
    def test_known_bad_crc_oracle_cannot_pass(self):
        self.assertIn('unresolved_or_missing_oracle_issues',validate({'status':'PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL','issues':['bad_crc'],'dshot_frames_sent':110000}))
    @staticmethod
    def good_t02():
        return {
            'status':'PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL',
            'issues':[], 'dshot_frames_sent':110000,
            'last_guest_virtual_elapsed_ns':110000000000,
            'completed_full_duration':True,
            'stages':[
                {'index':i,'kind':'hold','to_pct':10*i,
                 'frames_sent':10000,
                 'sampled_stage_gate':{'status':'PASS_SAMPLED_STAGE_DIAGNOSTIC'},
                 'valid_crc_feeds_observed':None,
                 'native_steps_observed':None} for i in range(11)],
            'autonomous':{
                'stage_physical_checkpoints':[
                    {'index':i,'valid':True,'complete':True,
                     'end_sent_cumulative':(i+1)*10000,
                     'declared_start_ms':i*10000,
                     'declared_end_ms':(i+1)*10000}
                    for i in range(11)],
                'event_timing_evidence':{'trace_triplets':91796},
                'neutral_teardown':{'qualified':True}}
        }

    def test_exact_full_t02_evidence_can_pass(self):
        self.assertEqual(validate(self.good_t02()),[])

    def test_missing_issues_not_assumed_empty(self):
        d=self.good_t02();del d['issues']
        self.assertIn('unresolved_or_missing_oracle_issues',validate(d))

    def test_mismatched_stage_command_not_a_full_sweep(self):
        d=self.good_t02();d['stages'][6]['to_pct']=50
        self.assertIn('stage_6_plan_or_frame_coverage_wrong',validate(d))

    def test_mismatched_latched_physical_boundary_fails(self):
        d=self.good_t02()
        d['autonomous']['stage_physical_checkpoints'][5]['declared_end_ms']=0
        self.assertIn('stage_5_declared_boundary_mismatch',validate(d))

    def test_legacy_fake_crc_observations_fail(self):
        d=self.good_t02();d['stages'][9]['valid_crc_feeds_observed']=100
        self.assertTrue(any('must_be_null_not_measured' in e for e in validate(d)))

    def test_absent_temporal_triplets_not_complete(self):
        d=self.good_t02()
        d['autonomous']['event_timing_evidence']['trace_triplets']=0
        self.assertIn('no_qemu_temporal_cross_cap_timg12_triplets',validate(d))

    def test_virtual_time_must_be_exact_duration(self):
        d=self.good_t02();d['last_guest_virtual_elapsed_ns']=110000000001
        self.assertIn('expected_exact_110s_guest_virtual_time',validate(d))

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
