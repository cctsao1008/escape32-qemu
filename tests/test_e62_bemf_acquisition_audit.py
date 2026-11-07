"""UNIT synthetic records only; no fabricated runtime motor evidence."""
import unittest
from tools.e62_bemf_acquisition_audit import analyze
class PointTests(unittest.TestCase):
    def log(self,enabled=False,capture=False):
        a='E62_P0_EVENT seq=1 vns=100 kind=CMP_FILTER a=1 b=0 c=2047 d=2047 e=0 f=0\n'
        a+=f'E62_BEMF_ACQ vns=100 source_seq=1 phase=1 level=0 ecctl0=45 ecctl1={257 if enabled else 1} ecctl2=144 eceint={34 if enabled else 0} ecflg=0 capture_index=0 frozen=0 pwm_counter=3294 pwm_period=3778 motor_sample_vns=95 motor_active=1 theta=5.23598775598 omega=80 ia=0 ib=0 ic=0 torque=0 mask=34 gate=1\n'
        if capture:a+='E62_P0_EVENT seq=2 vns=100 kind=CAP1 a=123 b=1 c=3 d=34 e=0 f=0\n'
        return a
    def test_disabled_edge_not_filled_with_fake_capture(self):
        r=analyze(self.log());self.assertEqual(len(r['matching_disabled_points']),1);self.assertIsNone(r['points'][0]['real_cap1']);self.assertEqual(r['points'][0]['motor_sample_age_ns'],5)
    def test_real_source_capture_must_exist_when_claimed(self):
        self.assertEqual(analyze(self.log(True,True))['points'][0]['classification'],'REAL_CAP1_SOURCE_OBSERVED')
        self.assertEqual(analyze(self.log(True,False))['points'][0]['classification'],'INCOMPLETE_EXPECTED_CAPTURE_CONTEXT')
    def test_inconsistent_source_or_future_sample_is_incomplete(self):
        for text in (self.log().replace('source_seq=1','source_seq=99'),self.log().replace('motor_sample_vns=95','motor_sample_vns=101'),self.log().replace('omega=80','omega=nan')):
            with self.assertRaises(ValueError):analyze(text)
if __name__=='__main__':unittest.main()
