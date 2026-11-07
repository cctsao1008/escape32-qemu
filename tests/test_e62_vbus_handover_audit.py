"""Synthetic UNIT flow records, never measured motor or hardware evidence."""
import copy,unittest
from tools.e62_vbus_handover_audit import audit,convert,parse
class FlowTests(unittest.TestCase):
    def fixture(self):
        events=[dict(kind='E62_VBUS_SOURCE',vns=0,frame=0,mv=24000,sensor_mode=0)];rows=[]
        for i,(raw,mv,code,sel,mux,edge) in enumerate(((1963,23000,2035,5,0,0),(2091,24500,2053,2,1,1))):
            t=1000+i*4000;counter=200+i*800;sample=i+11;base=8+i*3
            events += [dict(kind='E62_VBUS_SOURCE',vns=t,frame=i+1,mv=mv,sensor_mode=0),dict(kind='E62_VBUS_EOC',vns=t+200,sample=sample,acquisition=t+100,code=raw,channel=12,soc=1),dict(kind='E62_VBUS_READ',vns=t+300,sample=sample,code=raw),dict(kind='E62_DAC_SHADOW',vns=t+500,code=code,sample=sample,cap_enabled=0),dict(kind='E62_DAC_ACTIVE',vns=t+1000,code=code,mux=mux,edge=edge,cap_enabled=0,counter=counter,zero=i*3)]
            events += [dict(kind='E62_VBUS_ZERO',vns=t+1000+j*500,counter=counter+j*100,zero=i*3+j) for j in range(3)]
            common=dict(sample=sample,expected_code=code,active_code=code,blackout_epoch=2,selected_code=sel,fresh=1,latest_valid=1,max_age_ticks=32,age_ticks=1)
            rows += [dict(common,seq=base,event=8,published=0,armed=0),dict(common,seq=base+1,event=9,published=0,armed=0),dict(common,seq=base+2,event=6,published=1,ready=1,armed=1,ecap_counter=counter+210)]
        return events,dict(reference_observer=dict(entries=rows))
    def test_complete_specific_flow_derives_clock_not_assumes_it(self):
        e,f=self.fixture();r=audit(e,f);self.assertEqual(r['status'],'SPECIFIC_SOURCE_HANDOVERS_VERIFIED');self.assertEqual(r['handovers'][0]['observed_ecap_tick_ns'],5);self.assertFalse(r['rotor_synchronized'])
    def test_wrong_phase_epoch_or_unread_sample_stays_incomplete(self):
        e,f=self.fixture();next(r for r in e if r['kind']=='E62_DAC_ACTIVE')['mux']=2
        self.assertEqual(audit(e,f)['status'],'INCOMPLETE_HANDOVER_EVIDENCE')
        e,f=self.fixture();f['reference_observer']['entries'][1]['blackout_epoch']=3
        self.assertEqual(audit(e,f)['status'],'INCOMPLETE_HANDOVER_EVIDENCE')
        e,f=self.fixture();e=[r for r in e if r['kind']!='E62_VBUS_READ']
        self.assertEqual(audit(e,f)['status'],'INCOMPLETE_HANDOVER_EVIDENCE')
    def test_uncaptured_zero_or_wrong_conversion_not_waived(self):
        e,f=self.fixture();next(r for r in e if r['kind']=='E62_VBUS_EOC')['code']=1900
        self.assertTrue(audit(e,f)['source_errors'])
        e,f=self.fixture();f['reference_observer']['entries'][2]['ecap_counter']=310
        self.assertEqual(audit(e,f)['status'],'INCOMPLETE_HANDOVER_EVIDENCE')
    def test_stale_unarmed_or_mismatched_active_publication_stays_incomplete(self):
        for key,value in [('age_ticks',33),('armed',0),('active_code',1234),('max_age_ticks',0)]:
            e,f=self.fixture();f['reference_observer']['entries'][2][key]=value
            self.assertEqual(audit(e,f)['status'],'INCOMPLETE_HANDOVER_EVIDENCE')
        e,f=self.fixture();f['reference_observer']['entries'][2]['ecap_counter']+=1000000
        self.assertEqual(audit(e,f)['status'],'INCOMPLETE_HANDOVER_EVIDENCE')
    def test_host_result_access_is_not_guest_sampling(self):
        e,f=self.fixture();e+=parse(['[R +1] readl 0x4000b002'])
        self.assertIn('HOST_ADC_RESULT_ACCESS_CONFOUND',audit(e,f)['source_errors'])
    def fresh_invalid_fixture(self):
        events=[dict(kind='E62_VBUS_SOURCE',vns=0,frame=0,mv=24000,sensor_mode=0),dict(kind='E62_VBUS_SOURCE',vns=1000,frame=1,mv=24000,sensor_mode=1),dict(kind='E62_VBUS_EOC',vns=1200,acquisition=1100,sample=21,code=0,channel=12,soc=1),dict(kind='E62_VBUS_READ',vns=1300,sample=21,code=0)]
        events += [dict(kind='E62_VBUS_ZERO',vns=t,counter=c) for t,c in ((1000,100),(1500,200),(2000,300))]
        events += [dict(kind='SOURCE_LOG_COVERAGE_END',vns=3000)]
        common=dict(armed=1,published=1,ready=1,age_ticks=17,max_age_ticks=32,fresh=1,latest_valid=0)
        fault=dict(common,event=5,seq=1,ecap_counter=320);shutdown=dict(common,event=11,seq=2,ecap_counter=324);shutdown.update(armed=0,published=0,ready=0)
        return events,dict(reference_observer=dict(entries=[fault,shutdown]),native_motor=dict(actual_pwm_six_bit_mask=0))
    def test_native_fresh_invalid_requires_read_order_shutdown_and_future_capture_quiet(self):
        e,f=self.fresh_invalid_fixture();r=audit(e,f)
        self.assertEqual(r['invalid_only_before_expiry']['status'],'NATIVE_INVALID_ONLY_BEFORE_EXPIRY_VERIFIED')
        e,f=self.fresh_invalid_fixture();f['reference_observer']['entries'][0].update(fresh=0,age_ticks=33)
        self.assertEqual(audit(e,f)['invalid_only_before_expiry']['status'],'NOT_ISOLATED')
        e,f=self.fresh_invalid_fixture();e=[r for r in e if r['kind']!='E62_VBUS_READ']
        self.assertNotEqual(audit(e,f)['invalid_only_before_expiry']['status'],'NATIVE_INVALID_ONLY_BEFORE_EXPIRY_VERIFIED')
        e,f=self.fresh_invalid_fixture();e += [dict(kind='SOURCE_CAP1',vns=2200)]
        self.assertIn('CAP1_AFTER_SHUTDOWN',audit(e,f)['source_errors'])
    def test_local_counter_reset_is_not_absolute_time_evidence(self):
        e,f=self.fresh_invalid_fixture();next(r for r in e if r['kind']=='E62_VBUS_ZERO' and r['vns']==2000)['counter']=0
        self.assertIsNone(audit(e,f)['invalid_only_before_expiry']['fault_observation_mapping'])
    def test_invalid_input_not_reinterpreted_as_calibrated_midpoint(self):self.assertIsNone(convert(0))
if __name__=='__main__':unittest.main()
