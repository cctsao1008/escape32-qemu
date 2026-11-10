import unittest
from tools.e62_restart_adc_observability import observe
class TestAvailableADC(unittest.TestCase):
 def events(self,codes=(2100,2101,2101),epoch=1):
  out=[]
  for i,c in enumerate(codes):out.append(dict(seq=i+1,vns=100+i,kind='ADC_PHASE_EOC',a=i,b=c,e=epoch,f=0))
  for i,c in enumerate(codes):out.append(dict(seq=i+4,vns=110+i,kind='ADC_PHASE_READ',a=i,b=c,e=epoch,f=0))
  return out
 def test_single_code_tie_is_not_direction_or_standstill(self):
  r=observe(self.events(),200);self.assertFalse(r['direction_proven']);self.assertFalse(r['stationary_proven']);self.assertEqual(r['last_guest_read_sample']['spread_codes'],1)
 def test_missing_phase_is_incomplete(self):self.assertIsNone(observe(self.events()[:-1],200)['last_guest_read_sample'])
 def test_mismatched_epoch_is_not_substituted(self):
  e=self.events();e[-1]['e']=2;self.assertIsNone(observe(e,200)['last_guest_read_sample'])
 def test_future_sample_not_reused(self):self.assertIsNone(observe(self.events(),110)['last_guest_read_sample'])
