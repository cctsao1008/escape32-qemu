import unittest
from tools.ci.qualification_matrix import summarize

class QualificationMatrixTests(unittest.TestCase):
    def test_no_evidence_remains_open_not_pass(self):
        d=summarize()
        self.assertEqual(d['M1_T01']['status'],'OPEN_NOT_RUN')
        self.assertIn('KNOWN_FAIL',d['M4_STRICT_ROTOR_G13B3M']['status'])
        self.assertIn('OPEN_',d['M3_NATIVE_PHYSICAL_DSHOT_CRC']['status'])
        self.assertIn('OPEN_',d['M4_PHYSICS_GUEST_COUPLING']['status'])
        self.assertIn('NOT_PRODUCTION',d['overall']['status'])
    def test_performance_or_t02_pass_never_implies_board_or_rotor(self):
        fake=dict(status='PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL',
             dshot_frames_sent=11000,issues=[],
             stages=[dict(sampled_stage_gate=dict(status='PASS_SAMPLED_STAGE_DIAGNOSTIC'))]*2,
             autonomous=dict(neutral_teardown=dict(qualified=True)))
        d=summarize(t01=fake)
        self.assertEqual(d['M1_T01']['status'],'PASS_FUNCTIONAL_ONLY')
        self.assertIn('KNOWN_FAIL',d['M4_STRICT_ROTOR_G13B3M']['status'])
        self.assertEqual(d['M5_BOARD_THERMAL_FLIGHT']['status'],
                         'NOT_QUALIFIED_BY_QEMU')

    def test_native_bad_crc_is_independent_of_motor_and_fault_gates(self):
        crc={'status':'PASS_ORIGINAL_GUEST_PHYSICAL_BAD_CRC_REJECTED',
             'issues':[],
             'scope':'PHYSICAL_PA26_DSHOT600_SOURCE_CRC_AND_WWDT_FEED_ONLY'}
        d=summarize(crc_native=crc)
        self.assertEqual(d['M3_NATIVE_PHYSICAL_DSHOT_CRC']['status'],
                         'PASS_NATIVE_SOURCE_CRC_AND_FEED_ONLY')
        self.assertIn('KNOWN_FAIL',d['M4_STRICT_ROTOR_G13B3M']['status'])
        self.assertIn('OPEN_',d['M3_SIM_ONLY_FAULT_NEGATIVE_GATES']['status'])
