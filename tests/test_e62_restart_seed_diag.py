import unittest
from tools.e62_restart_seed_diag import snapshot
class TestRestartRecord(unittest.TestCase):
 def test_refusal_is_not_success(self):
  words=[100,4,5,4700,0,2];d=snapshot(lambda a:words[a//4],0)
  self.assertEqual(d['status'],'REFUSAL_NOT_REACQUISITION');self.assertEqual(d['oldstep'],4)
 def test_observation_is_not_application(self):
  words=[100,4,5,4700,1300,3];self.assertEqual(snapshot(lambda a:words[a//4],0)['status'],'OBSERVED_NOT_APPLIED')
 def test_unavailable_is_incomplete(self):self.assertEqual(snapshot(lambda a:0,0)['status'],'INCOMPLETE_NO_RECORD')
 def test_changing_rejected(self):
  calls=[0]
  def read(a):calls[0]+=1;return 1 if calls[0]>6 else 0
  with self.assertRaises(RuntimeError):snapshot(read,0)
