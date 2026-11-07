import struct,unittest
from tools.e62_reference_observer import snapshot_bulk,NAMES
class BulkTests(unittest.TestCase):
    def fixture(self):
        lo=0x20001000;addresses=dict(zip(NAMES,(lo+25600,lo+20480,lo)))
        b=bytearray(25604);r=[1,6,100,500,1,0,700,700,1,1,1,1,20,99,99,32,2,1,1,20]
        struct.pack_into('<20I',b,20480,*r);struct.pack_into('<I',b,25600,1)
        return addresses,b
    def test_stable_records_never_imply_source_or_motor_qualification(self):
        a,b=self.fixture();r=snapshot_bulk(lambda addr,n:bytes(b),a)
        self.assertEqual(len(r['entries']),1);self.assertFalse(r['source_publication_proven'])
    def test_torn_or_overwritten_record_is_explicitly_incomplete(self):
        a,b=self.fixture();copies=[bytes(b),bytearray(b)];struct.pack_into('<I',copies[1],20480,2)
        r=snapshot_bulk(lambda addr,n:copies.pop(0),a)
        self.assertEqual(r['rejected_unstable_sequences'],[1]);self.assertEqual(r['entries'],[])
    def test_growing_head_preserves_stable_prefix_and_missing_tail(self):
        a,b=self.fixture();c=bytearray(b);struct.pack_into('<I',c,25600,2);copies=[bytes(b),bytes(c)]
        r=snapshot_bulk(lambda addr,n:copies.pop(0),a)
        self.assertEqual(len(r['entries']),1);self.assertIn((2,2),r['missing_sequence_ranges']);self.assertFalse(r['history_complete'])
if __name__=='__main__':unittest.main()
