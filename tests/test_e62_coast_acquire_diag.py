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
