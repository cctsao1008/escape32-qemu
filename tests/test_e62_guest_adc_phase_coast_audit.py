#!/usr/bin/env python3
"""E62 #5 source-owned Original Guest ADC epoch negative tests."""
import copy
import unittest
from tools.e62_guest_adc_phase_coast_audit import (
    correlate_guest_phase_epochs, contrast_in_window, validate_source)

def sample(n=5):
    e=[]
    seq=0
    for t in range(1,n+1):
        for i,(soc,ch) in enumerate(((1,12),(2,2),(1,5))):
            at=1_000_000*t+100*i
            val=2010+10*i+t
            seq+=1
            e.append(dict(vns=at,kind="ADC_PHASE_EOC",
                          data=(i,val,ch,soc,t,0)))
        for i,(soc,ch) in enumerate(((1,12),(2,2),(1,5))):
            at=1_000_000*t+5000+100*i
            val=2010+10*i+t
            seq+=1
            e.append(dict(vns=at,kind="ADC_PHASE_READ",
                          data=(i,val,ch,soc,t,0)))
    return e

class RealGuestADCSource(unittest.TestCase):
    def test_true_complete_eoc_to_guest_read_epoch(self):
        triplets,counts=correlate_guest_phase_epochs(sample(60))
        self.assertEqual(len(triplets),60)
        self.assertEqual(counts,{"eoc":180,"read":180})
        w=contrast_in_window(triplets,1_000_000,61_000_000)
        self.assertEqual(w["classification"],
                         "GUEST_ADC_PHASE_CONTRAST_PRESENT_DIRECTION_UNPROVEN")
        self.assertFalse(w["direction_qualified"])

    def test_single_code_gap_cannot_authorize_direction(self):
        t=[{"vns":i*1_000_000,"codes":[2048,2048,2049]}
           for i in range(60)]
        verdict=contrast_in_window(t,0,60_000_000)
        self.assertEqual(verdict["classification"],
                         "INSUFFICIENT_QUANTIZED_GUEST_ADC_CONTRAST")
        self.assertFalse(verdict["rotor_phase_qualified"])

    def test_missing_phase_or_guest_read_fails(self):
        e=sample()
        e=[r for r in e if not (r["kind"]=="ADC_PHASE_READ" and
                                r["data"][0]==1 and r["data"][4]==3)]
        with self.assertRaisesRegex(ValueError,"Missing|Unconsumed"):
            correlate_guest_phase_epochs(e)

    def test_stale_and_early_guest_reads_fail(self):
        e=sample()
        r=next(x for x in e if x["kind"]=="ADC_PHASE_READ" and
               x["data"][0]==0 and x["data"][4]==2)
        r["vns"]+=6_000_000
        with self.assertRaisesRegex(ValueError,"fresh"):
            correlate_guest_phase_epochs(e)

    def test_wrong_soc_or_channel_fails(self):
        e=sample()
        target=next(x for x in e if x["kind"]=="ADC_PHASE_EOC")
        target["data"]=(0,2020,13,1,1,0)
        with self.assertRaisesRegex(ValueError,"SOC/channel"):
            correlate_guest_phase_epochs(e)

    def test_forged_read_code_fails(self):
        e=sample()
        target=next(x for x in e if x["kind"]=="ADC_PHASE_READ")
        a=list(target["data"]);a[1]+=1;target["data"]=tuple(a)
        with self.assertRaisesRegex(ValueError,"does not match"):
            correlate_guest_phase_epochs(e)

    def test_duplicate_epoch_fails(self):
        e=sample()
        e.insert(1,e[0].copy())
        with self.assertRaisesRegex(ValueError,"duplicate"):
            correlate_guest_phase_epochs(e)

    def test_unconsumed_eoc_fails(self):
        e=sample()
        e=[x for x in e if not (x["kind"]=="ADC_PHASE_READ" and
                               x["data"][4]==5)]
        with self.assertRaisesRegex(ValueError,"Unconsumed"):
            correlate_guest_phase_epochs(e)

    def test_cross_phase_skew_fails(self):
        e=sample()
        target=next(x for x in e if x["kind"]=="ADC_PHASE_READ" and
                    x["data"][0]==2 and x["data"][4]==2)
        target["vns"]+=5_100_000
        with self.assertRaisesRegex(ValueError,"fresh|triplet"):
            correlate_guest_phase_epochs(e)

if __name__=="__main__":
    unittest.main(verbosity=2)
