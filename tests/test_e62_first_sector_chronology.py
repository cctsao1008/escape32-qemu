"""Synthetic unit records; never motor, firmware or hardware measurements."""
import tempfile,struct,unittest
from pathlib import Path
from tools.e62_first_sector_chronology import analyze,state,phase_of
from tools.e62_first_sector_campaign import validate_cfg_separation
class ChronologyTests(unittest.TestCase):
    def events(self):
        rows=[('DSHOT',100,dict(a=0,c=448)),('PWM_PAIR',101,dict(a=8,b=24)),('SWITCH_FOCUS',101,dict(a=24,b=1,c=15)),('ROTOR',130,dict(a=100000,b=1800,d=-1000,e=1000,f=-500000)),('CAP1',200,{}),('CAP1_ACK',201,{}),('ECAP1_CAP1_READ',202,{}),('T12_LOAD',203,{}),('T12_START',204,{}),('ROTOR',210,dict(a=100000,b=2000,f=-500000)),('TIMG12',300,{}),('PWM_PAIR',320,dict(a=2,b=9)),('ROTOR',330,dict(a=-51000,b=2200,f=-500000))]
        return [dict(dict(a=0,b=0,c=0,d=0,e=0,f=0),**v,kind=k,vns=t,seq=i+1) for i,(k,t,v) in enumerate(rows)]
    def test_negative_samples_split_pre_acceptance_wait_and_after_physical_change(self):
        r=analyze(self.events(),{},(90,350))['demands'][0]
        self.assertEqual({k:v['count'] for k,v in r['negative_torque_samples_by_feedback_phase'].items()},dict(BEFORE_ACCEPTED_CAPTURE=1,SCHEDULED_WAIT_BEFORE_IRQ=1,AFTER_FIRST_PHYSICAL_PAIR_CHANGE=1))
        self.assertEqual(r['first_sector_negative_samples'],2)
        self.assertEqual(r['first_guest_decisions_order_correlated'],[])
    def test_bounded_gate_not_extrapolated_outside_window_or_after_limit(self):
        es=self.events();self.assertEqual(state(es,210,(90,350))['pads']['mask'],24)
        self.assertIsNone(state(es,210,(220,350))['pads'])
        es += [dict(kind='SWITCH_FOCUS_LIMIT',vns=205)]
        self.assertIsNone(state(es,210,(90,350))['pads'])
    def test_acceptance_transition_and_missing_acceptance_stay_explicit(self):
        self.assertEqual(phase_of(202,200,204,300,320),'CAPTURE_TO_SCHEDULE_TRANSITION')
        self.assertEqual(phase_of(250,None,None,None,None),'NO_OBSERVED_ACCEPTED_CAPTURE')
        es=self.events();es[3]['seq']+=1
        with self.assertRaises(ValueError):analyze(es,{})
    def test_reused_restart_pair_is_derived_from_real_pad_edge_not_invented_pwm_pair(self):
        es=self.events();es=[e for e in es if not(e['kind']=='PWM_PAIR' and e['vns']==101)]
        for n,e in enumerate(es):e['seq']=n+1
        r=analyze(es,{},(90,350))['demands'][0]
        self.assertEqual(r['first_pair']['source']['kind'],'SWITCH_FOCUS')
        self.assertTrue(r['first_pair']['pair_id_derived_from_pad_mask'])
        self.assertEqual(r['first_pair']['pair_id'],8)
        self.assertEqual(r['first_changed_pair']['pair_id'],2)
        self.assertEqual(r['first_sector_negative_samples'],2)

    def test_program_header_overlap_fails_before_vm_launch(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.elf';cfg=Path(d)/'cfg';cfg.write_bytes(bytes(336));data=bytearray(84);data[:6]=b'\x7fELF\x01\x01';struct.pack_into('<I',data,28,52);struct.pack_into('<HH',data,42,32,1)
            struct.pack_into('<8I',data,52,1,0,0,0,0x10700,0x10700,5,0x10000);p.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'overlaps'):validate_cfg_separation(p,cfg)
            struct.pack_into('<I',data,64,0x6000);p.write_bytes(data);validate_cfg_separation(p,cfg)
if __name__=='__main__':unittest.main()
