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
        # Self-declared aggregate/stage PASS without physical checkpoints,
        # time, and temporal association must fail closed.
        self.assertEqual(d['M1_T01']['status'],'FAIL_FUNCTIONAL_GATE')
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

    def test_original_t01_physical_evidence_accepts_only_full_gate(self):
        from test_t02_t01_strict_qualification import t01
        d=summarize(t01=t01())
        self.assertEqual(d['M1_T01']['status'],'PASS_FUNCTIONAL_ONLY')

    def test_false_green_fault_summary_is_rejected(self):
        names=['nfault','oc-u','oc-v','oc-w']
        counterfeit={'independent_cases_passed':names,
                     'issues':['oc-u:no_original_irq'],
                     'status':'FAIL_INDEPENDENT_FAULT_GATE',
                     'scope':'MODEL_ONLY_NATIVE_NEUTRAL_NOT_MOTOR_RUNNING'}
        d=summarize(fault_native=counterfeit)
        self.assertIn('OPEN_OR_FAIL',d['M3_SIM_ONLY_FAULT_NEGATIVE_GATES']['status'])

    def test_independent_complete_fault_summary_can_pass_modeled_scope(self):
        names=['nfault','oc-u','oc-v','oc-w']
        valid={'independent_cases_passed':names,
               'issues':[],
               'status':'PASS_SIM_ONLY_EXTERNAL_FAULT_IRQ_SHUTDOWN_ONLY',
               'scope':'MODEL_ONLY_NATIVE_NEUTRAL_NOT_MOTOR_RUNNING'}
        d=summarize(fault_native=valid)
        self.assertEqual(d['M3_SIM_ONLY_FAULT_NEGATIVE_GATES']['status'],
                         'PASS_MODELED_GUEST_FAULT_GATES')
        self.assertIn('KNOWN_FAIL',d['M4_STRICT_ROTOR_G13B3M']['status'])
