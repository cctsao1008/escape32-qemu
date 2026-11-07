import unittest
from tools.e62_coast_acquire_diag import snapshot
class TestCoastRecord(unittest.TestCase):
 def test_refusal_not_pass(self):
  w=[0]*12;w[9]=2;self.assertEqual(snapshot(lambda a:w[a//4],0)['status'],'REFUSED_BEFORE_POWER_NOT_REACQUISITION')
 def test_two_edges_not_rotor_qualification(self):
  w=[0]*12;w[9]=4;r=snapshot(lambda a:w[a//4],0);self.assertFalse(r['original_qualified']);self.assertEqual(r['status'],'TWO_CAPTURES_NOT_ROTOR_QUALIFICATION')
 def test_unstable_record_rejected(self):
  n=[0]
  def read(a):n[0]+=1;return 1 if n[0]>12 else 0
  with self.assertRaises(RuntimeError):snapshot(read,0)

class TestPendingReference(unittest.TestCase):
 def test_phase_can_expire_before_calibration_age(self):
  from tools.e62_coast_acquire_diag import pending_reference
  addresses={'reference_valid':0,'tick':4,'blackout_epoch':8,'reference_latest':12}
  words={0:1,4:100,8:2,12:1000|(1000<<16),16:1000,20:7,24:74,28:74,32:32,36:2}
  r=pending_reference(lambda a:words[a],addresses);self.assertTrue(r['inside_age_bound']);self.assertEqual(r['age_ticks'],26)
 def test_invalid_is_not_promoted_by_age(self):
  from tools.e62_coast_acquire_diag import pending_reference
  addresses={'reference_valid':0,'tick':4,'blackout_epoch':8,'reference_latest':12}
  r=pending_reference(lambda a:0,addresses);self.assertEqual(r['valid_flag'],0);self.assertFalse(r['inside_age_bound'])
