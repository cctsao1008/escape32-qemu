"""Fail-closed one-ELF L1 release gate, separate from L2 rotor qualification."""
import json
import tempfile
import unittest
from pathlib import Path
from tools.ci.firmware_release_l1 import check_evidence, MARKERS, RELEASE_STATUS
from test_t02_t01_strict_qualification import t01
from test_t02_independent_gate import T02IndependentStrictGateTests as Fixture

def crc_record(frame, callback, feeds, guest_throttle):
    return {
        'frame':frame,'guest_frame':frame,'delivered':32,
        'capture':32,'dma_beats':32,'callback_return':callback,
        'throttle_pre_callback':0,
        'throttle_after_callback':guest_throttle,
        'watchdog_valid_feeds_delta':feeds,
        'gate_output_inactive_after_callback':True,'ipsr':0,
    }

def fault_record(kind):
    return {
        'fault':kind,'irq_ipsr':44,
        'shutdown_pc':0x1000,
        'shutdown_pc_hit':0x1000,
        'tzflags':0x20000 if kind=='nfault' else 0x40000,
        'interrupt_flags':4,'gate_inactive':True
    }

class L1ReleaseContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        files={
            'e62-l1-t01.json':t01(),
            'e62-l1-t02.json':Fixture.good_t02(),
            'e62-l1-dshot-valid.json':[crc_record(0x1230,1,1,953)],
            'e62-l1-dshot-badcrc.json':[crc_record(0x1231,0,0,0)]
        }
        for kind in ('nfault','oc-u','oc-v','oc-w'):
            files['e62-l1-fault-'+kind+'.json']=fault_record(kind)
        for name,data in files.items():
            (self.root/name).write_text(json.dumps(data))
        for name,marker in MARKERS.items():
            (self.root/('e62-l1-'+name+'.log')).write_text(
                marker+'\n')

    def test_full_unmodified_guest_l1_evidence_is_limited_functional_pass(self):
        record=check_evidence(self.root)
        self.assertEqual(record['issues'],[])
        self.assertEqual(record['status'],RELEASE_STATUS)
        self.assertIn('KNOWN_FAIL',record['G13B3M_strict_rotor'])
        self.assertIn('OPEN',record['Guest_coupled_motor_physics'])
        self.assertEqual(record['hardware_qualification'],'NOT_QUALIFIED')

    def test_missing_T02_is_not_silent_success(self):
        (self.root/'e62-l1-t02.json').unlink()
        record=check_evidence(self.root)
        self.assertEqual(record['status'],'FAIL_L1_RELEASE_EVIDENCE')
        self.assertIn('missing:e62-l1-t02.json',record['issues'])

    def test_self_reported_T01_pass_with_no_physical_stages_is_rejected(self):
        f=self.root/'e62-l1-t01.json'
        d=json.loads(f.read_text())
        d['autonomous']['stage_physical_checkpoints']=[]
        f.write_text(json.dumps(d))
        record=check_evidence(self.root)
        self.assertTrue(any(x.startswith('T01:') for x in record['issues']))

    def test_dshot_one_bit_crc_must_produce_zero_source_feed(self):
        f=self.root/'e62-l1-dshot-badcrc.json'
        d=json.loads(f.read_text())
        d[0]['watchdog_valid_feeds_delta']=1
        f.write_text(json.dumps(d))
        record=check_evidence(self.root)
        self.assertTrue(any(x.startswith('DShot_CRC:') for x in record['issues']))

    def test_missing_fault_shutdown_is_rejected(self):
        f=self.root/'e62-l1-fault-oc-u.json'
        d=json.loads(f.read_text())
        d['gate_inactive']=False
        f.write_text(json.dumps(d))
        record=check_evidence(self.root)
        self.assertTrue(any(x.startswith('OC_nFAULT:') for x in record['issues']))

    def test_missing_bootrst_output_marker_not_accepted(self):
        (self.root/'e62-l1-wwdt_bootrst.log').write_text('no output\n')
        record=check_evidence(self.root)
        self.assertTrue(any('wwdt_bootrst' in x for x in record['issues']))

    def test_l2_fail_cannot_be_hidden_by_l1(self):
        d=check_evidence(self.root)
        self.assertTrue(d['status'].startswith('PASS_L1_'))
        self.assertIn('KNOWN_FAIL',d['G13B3M_strict_rotor'])
