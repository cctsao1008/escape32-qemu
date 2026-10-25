import unittest
from tools.ci.dshot_crc_qualification import verify_pair

def record(frame,crc,feeds,before,after):
    return {'frame':frame,'guest_frame':frame,'delivered':32,'capture':32,
            'dma_beats':32,'gate_output_inactive_after_callback':True,
            'ipsr':0,'callback_return':crc,'watchdog_valid_feeds_delta':feeds,
            'throttle_pre_callback':before,'throttle_after_callback':after}

class NativePhysicalCRCQualification(unittest.TestCase):
    def test_source_crc_valid_and_bad_wire_can_qualify(self):
        a=[record(0x1230,1,1,0,900)]
        b=[record(0x1231,0,0,0,0)]
        self.assertEqual(verify_pair(a,b),[])
    def test_source_wwdt_feed_on_invalid_fails(self):
        a=[record(0x1230,1,1,0,900)]
        b=[record(0x1231,0,1,0,0)]
        self.assertIn('invalid_frame_rejection_or_wwdt_feed_incorrect',
                      verify_pair(a,b))
    def test_callback_without_real_dma_fails(self):
        a=[record(0x1230,1,1,0,900)]
        b=[record(0x1231,0,0,0,0)]
        b[0]['dma_beats']=0
        self.assertIn('invalid:wire_capture_dma_callback_mismatch',
                      verify_pair(a,b))
    def test_bad_crc_must_not_change_dshot_payload(self):
        a=[record(0x1230,1,1,0,900)]
        b=[record(0x123f,0,0,0,0)]
        self.assertIn('not_single_crc_bit_physical_negative_control',
                      verify_pair(a,b))
