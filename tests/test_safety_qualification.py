import unittest
from tools.ci.safety_qualification import verify_all

class SafetyQualificationTests(unittest.TestCase):
    @staticmethod
    def cases():
        return {k:{'fault':k,'irq_ipsr':44,'shutdown_pc_hit':22,
                   'shutdown_pc':22,'tzflags':0x20000 if k=='nfault' else 0x40000,
                   'interrupt_flags':4,'gate_inactive':True}
                for k in ('nfault','oc-u','oc-v','oc-w')}
    def test_four_original_guest_fault_cases_can_pass(self):
        d=verify_all(self.cases())
        self.assertEqual(d['issues'],[])
        self.assertEqual(d['status'],'PASS_SIM_ONLY_EXTERNAL_FAULT_IRQ_SHUTDOWN_ONLY')
        self.assertIn('OPEN_',d['signal_loss_watchdog_recovery'])
    def test_missing_fault_cannot_be_hidden(self):
        f=self.cases();del f['oc-w']
        d=verify_all(f)
        self.assertIn('oc-w:missing_artifact',d['issues'])
    def test_source_shutdown_gate_missing_fails(self):
        f=self.cases();f['nfault']['shutdown_pc_hit']=33
        self.assertTrue(verify_all(f)['issues'])
