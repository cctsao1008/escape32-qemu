import unittest
from tools.e62_rr_source_compare import compare,parse

class RRTests(unittest.TestCase):
    def setUp(self):
        self.rows=parse('E62_P0_EVENT seq=1 vns=100 kind=DSHOT a=0 b=0 c=0 d=0 e=0 f=0')
        self.rec={'differential_rr_mode':'record','qemu_exit_code_after_probe':0,'differential_rr_graceful_shutdown':True,'configured_dshot_frames':1,'passive_source_dshot_completed':1,'wiring_failure_reasons':[],'candidate_elf_sha256':'a'*64,'native_dshot_scenario':{'sha256':'b'*64},'effective_sim_profile':{'profile':'test'}}
        self.rep={**self.rec,'differential_rr_mode':'replay','status':'FAIL_HOST_FINAL_POLL','exception':'QEMU exited'}
    def test_exact_source_does_not_recover_host_observations_or_qualify_motor(self):
        out=compare(self.rows,self.rows,self.rec,self.rep)
        self.assertEqual(out['status'],'PASS_EXACT_SOURCE_RR_REPLAY')
        self.assertEqual(out['host_replay_status'],'FAIL_HOST_FINAL_POLL')
        self.assertFalse(out['p1_qualified']);self.assertFalse(out['host_missing_observations_reconstructed'])
    def test_timestamp_mismatch_not_hidden_by_same_payload_and_counts(self):
        other=[(1,101,*self.rows[0][2:])]
        self.assertEqual(compare(self.rows,other,self.rec,self.rep)['status'],'FAIL_SOURCE_RR_MISMATCH')
    def test_missing_dshot_and_unfinalized_record_rejected(self):
        with self.assertRaises(ValueError):compare(self.rows,[],self.rec,self.rep)
        with self.assertRaises(ValueError):compare(self.rows,self.rows,{**self.rec,'differential_rr_graceful_shutdown':False},self.rep)
    def test_different_firmware_identity_rejected(self):
        with self.assertRaises(ValueError):compare(self.rows,self.rows,self.rec,{**self.rep,'candidate_elf_sha256':'c'*64})
    def test_malformed_missing_and_backwards_events_rejected(self):
        for text in ('','E62_P0_EVENT broken','E62_P0_EVENT seq=2 vns=100 kind=DSHOT a=0 b=0 c=0 d=0 e=0 f=0'):
            with self.assertRaises(ValueError):parse(text)

if __name__=='__main__':unittest.main()
