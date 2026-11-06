"""UNIT memory maps, not measured or executed reference evidence."""
import unittest
from tools.e62_reference_observer import decode,snapshot,NAMES


def row():return [1,4,100,500,1,0,700,700,1,1,1,1,20,99,99,32,2,1,1,20]


class ReferenceTests(unittest.TestCase):
    def test_positive_state_is_not_source_or_motor_qualification(self):
        r=decode(row(),1);self.assertEqual(r['violations'],[]);self.assertEqual(r['age_ticks'],1)

    def test_missing_stale_invalid_phase_and_wrong_dac_fail(self):
        for index,value,reason in ((9,0,'ARMED_WITHOUT_VALID_PUBLICATION'),
            (13,50,'ARMED_STALE_REFERENCE'),(4,0,'ARMED_INVALID_PHASE'),
            (7,701,'ARMED_DAC_MISMATCH'),(17,0,'ARMED_WITHOUT_VALID_PUBLICATION')):
            with self.subTest(reason=reason):
                r=row();r[index]=value;self.assertIn(reason,decode(r,1)['violations'])

    def test_delayed_unarmed_publication_is_not_capture_permission(self):
        r=row();r[1]=2;r[9]=r[10]=r[11]=0;r[7]=699
        self.assertEqual(decode(r,1)['violations'],[])

    def test_sequence_commit_and_torn_snapshot_are_rejected(self):
        with self.assertRaises(ValueError):decode(row(),2)
        addresses=dict(zip(NAMES,(0x100,0x1000,0x3000)))
        memory={0x100:1,**{0x1000+i*4:v for i,v in enumerate(row())}}
        count=0
        def read(addr):
            nonlocal count
            if addr==0x100:
                count+=1
                return count
            return memory[addr]
        with self.assertRaises(RuntimeError):snapshot(read,addresses)

    def test_no_records_are_incomplete_and_no_feedback_interface_exists(self):
        r=snapshot(lambda addr:0,dict(zip(NAMES,(1,2,3))))
        self.assertEqual(r['status'],'INCOMPLETE');self.assertFalse(r['source_publication_proven'])


if __name__=='__main__':unittest.main()
