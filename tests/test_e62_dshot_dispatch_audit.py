import unittest
from tools.e62_dshot_dispatch_audit import classify,audit
from tools.ci.prepare_e62_timer_observer import patch,BEFORE,CALL,CONTEXT
class DispatchTests(unittest.TestCase):
    def test_decomposition_does_not_waive_small_failures(self):
        base=dict(frame=1,epoch=100,deadline=1000100,snapshot=1000100,callback=1000100,wave=1000100,event=1000100)
        self.assertEqual(classify(base),'WITHIN_EXISTING_BUDGET')
        for field,label in [('snapshot','DISPATCH_SNAPSHOT_LATE'),('callback','CLOCK_ADVANCED_BETWEEN_DISPATCH_SNAPSHOT_AND_CALLBACK'),('wave','CLOCK_ADVANCED_INSIDE_CALLBACK_BEFORE_WAVE'),('event','EVENT_OBSERVATION_AFTER_WAVE_SCHEDULING')]:
            r={**base,field:1000632,'event':1000632};self.assertEqual(classify(r),label)
    def test_incomplete_or_missing_diagnostics_are_not_zero_latency(self):
        with self.assertRaises(ValueError):audit([])
    def test_source_context_patch_is_guarded_and_idempotent(self):
        s='typedef struct QEMUClock {\n'+BEFORE+'\n'+CALL
        out=patch(s);self.assertIn(CONTEXT,out);self.assertEqual(patch(out),out)
        with self.assertRaises(ValueError):patch('wrong version')
if __name__=='__main__':unittest.main()
