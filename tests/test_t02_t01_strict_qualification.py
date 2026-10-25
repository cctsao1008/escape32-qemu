import copy
import unittest
from tools.ci.verify_t01 import validate

def t01():
    return {
        'status':'PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL','issues':[],
        'dshot_frames_sent':11000,'last_guest_virtual_elapsed_ns':11000000000,
        'stages':[{
            'sampled_stage_gate':{'status':'PASS_SAMPLED_STAGE_DIAGNOSTIC'},
            'valid_crc_feeds_observed':None,'native_steps_observed':None
        } for _ in range(2)],
        'autonomous':{
            'stage_physical_checkpoints':[
                {'valid':True,'complete':True,'index':i,
                 'end_sent_cumulative':n}
                for i,n in enumerate((1000,11000))],
            'neutral_teardown':{'qualified':True},
            'event_timing_evidence':{'trace_triplets':10052}
        }
    }

class OriginalGuestT01IndependentGate(unittest.TestCase):
    def test_valid_full_T01_strict_functional_scope_only(self):
        self.assertEqual(validate(t01()),[])
    def test_false_pass_without_stage_physical_wire_counts(self):
        d=t01(); d['autonomous']['stage_physical_checkpoints']=[]
        self.assertIn('expected_two_complete_ramp_hold_stages',validate(d))
    def test_false_pass_when_guest_per_wfi_counters_faked_zero(self):
        d=t01(); d['stages'][0]['native_steps_observed']=0
        self.assertTrue(any('must_be_not_measured_null' in s for s in validate(d)))
    def test_false_pass_missing_temporal_evidence(self):
        d=t01();d['autonomous']['event_timing_evidence']['trace_triplets']=0
        self.assertIn('missing_bemf_cap1_timg12_temporal_associations',validate(d))
    def test_t02_or_short_smoke_not_accepted(self):
        d=t01();d['dshot_frames_sent']=110000
        self.assertIn('expected_11000_dshot_frames',validate(d))
    def test_missing_issue_field_not_assumed_clean(self):
        d=t01();del d['issues']
        self.assertIn('unresolved_or_missing_oracle_issues',validate(d))
