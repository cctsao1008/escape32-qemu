"""UNIT negative evidence fixtures, never supplied as native motor feedback."""
import unittest
from tools.e62_pending_timer_fault_audit import audit
class PendingFaultTests(unittest.TestCase):
    def fixture(self):
        def e(t,k,a=0,b=0,c=0):return dict(seq=0,vns=1_500_000_000+t,kind=k,a=a,b=b,c=c,d=0,e=0,f=0)
        es=[e(100,'DSHOT',1500,200,200),e(1100,'CAP1',100),e(1200,'CAP1_ACK',c=100),e(2100,'ECAP1_CAP1_READ',100,300),e(2150,'T12_LOAD',199999,100000000),e(2200,'T12_START',199999,100000000),e(22000,'T12_STOP',198020,199999,1),e(22100,'SWITCH_FOCUS'),e(100000000,'DSHOT')]
        self.number(es)
        j={'reference_observer':{'entries':[dict(event=5,ecap_counter=4100,latest_valid=0,fresh=1)]},'pwm_source_after':{'instantaneous_six_pad_mask':0,'running':False}}
        return es,j
    def number(self,es):
        for n,row in enumerate(es,1):row['seq']=n
    def test_requires_running_counter_not_absent_irq(self):
        es,j=self.fixture();r=audit(es,j);self.assertEqual(r['status'],'PASS_NEW');self.assertTrue(r['pending_cancellation_proven']);self.assertFalse(r['continuous_pad_safety_proven'])
        es[6]['a']=0;self.assertNotEqual(audit(es,j)['status'],'PASS_NEW')
    def test_counter_and_load_must_match_scheduled_deadline(self):
        es,j=self.fixture();es[6]['a']+=200;self.assertEqual(audit(es,j)['status'],'FAIL')
        es,j=self.fixture();es[6]['b']-=1;self.assertEqual(audit(es,j)['status'],'FAIL')
    def test_missing_invalidity_or_source_is_incomplete(self):
        es,j=self.fixture();j['reference_observer']['entries']=[];self.assertEqual(audit(es,j)['status'],'INCOMPLETE')
        es,j=self.fixture();es[4]['seq']+=1;self.assertEqual(audit(es,j)['status'],'INCOMPLETE')
    def test_no_pass_with_subsequent_power_or_timer(self):
        for kind in ('PWM_PAIR','T12_START','TIMG12','CAP1_ACK'):
            es,j=self.fixture();es.insert(-1,dict(es[6],vns=1_500_030_000,kind=kind));self.number(es);self.assertEqual(audit(es,j)['status'],'FAIL')
    def test_clock_mapping_and_reference_freshness_are_evidence(self):
        es,j=self.fixture();es[3]['b']+=20;self.assertEqual(audit(es,j)['status'],'INCOMPLETE')
        es,j=self.fixture();j['reference_observer']['entries'][0]['fresh']=0;self.assertEqual(audit(es,j)['status'],'FAIL')
    def test_post_deadline_control_never_proves_cancellation(self):
        es,j=self.fixture();es[6]['kind']='TIMG12';es[6]['a']=1;es[6]['vns']=1_502_002_200;es[7]['vns']=1_503_002_200;j['reference_observer']['entries'][0]['ecap_counter']=600100;self.number(es)
        r=audit(es,j,expect_pending=False);self.assertEqual(r['status'],'PASS_NEW');self.assertFalse(r['pending_cancellation_proven'])
    def test_missing_source_demand_never_assumes1500ms(self):
        es,j=self.fixture();es[0]['c']=0;self.assertEqual(audit(es,j)['status'],'INCOMPLETE')
    def test_replacement_invalidates_old_deadline(self):
        es,j=self.fixture();es.insert(6,dict(es[5],vns=1_500_010_000));self.number(es);self.assertEqual(audit(es,j)['status'],'FAIL')
if __name__=='__main__':unittest.main()
