"""Only the checksum is corrupted, never the Guest decoded SRAM."""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'tests') not in sys.path:
    sys.path.insert(0,str(ROOT/'tests'))
from g13b_native_dshot import encode_dshot_physical_frame

class BadPhysicalDshotCRCContract(unittest.TestCase):
    def test_exactly_one_crc_bit_mutated(self):
        for cmd in (48,1000,2047):
            good=encode_dshot_physical_frame(cmd)
            bad=encode_dshot_physical_frame(cmd,corrupt_crc=True)
            self.assertEqual(bad,good^1)
            self.assertEqual((bad>>4),(good>>4))
            data=bad>>4
            checksum=(data^(data>>4)^(data>>8))&15
            self.assertNotEqual(checksum,bad&15)
    def test_default_crc_remains_bit_identical(self):
        self.assertEqual(encode_dshot_physical_frame(1000),
                         encode_dshot_physical_frame(1000,corrupt_crc=False))
