#!/usr/bin/env python3
"""E62 #5 source-owned Original Guest ADC epoch negative tests."""
import copy
import unittest
import json
import tempfile
from pathlib import Path
from tools.e62_guest_adc_phase_coast_audit import (
    correlate_guest_phase_epochs, contrast_in_window, validate_source,
    rank_motion_diagnostic, RANK_SEQUENCE, load_rank_profile)

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

    def test_rank_motion_only_candidate_never_authorizes_rearm(self):
        # Construct all six six-permutation phase orderings, then repeat
        # advancing rank in one direction. Deliberately unlinked to angle.
        volts=(2100,2050,2000)
        rec=[]
        for i in range(9):
            order=RANK_SEQUENCE[i%6]
            v=[0,0,0]
            for p,phase in enumerate(order):
                v[phase]=volts[p]
            rec.append({"vns":i*1_000_000,"codes":v})
        x=rank_motion_diagnostic(rec)
        self.assertTrue(x["diagnostic_consistent_rank_sequence_candidate_only"])
        self.assertFalse(x["Guest_windmill_direction_or_angle_qualified"])
        self.assertFalse(x["motor_rearm_permitted"])

    def test_skips_mixed_direction_and_ties_never_count_as_confidence(self):
        def values(index):
            order=RANK_SEQUENCE[index]
            out=[0,0,0]
            for i,p in enumerate(order):
                out[p]=[2100,2050,2000][i]
            return out
        for ids in ([0,2,4,0],[0,1,0,1,0]):
            rec=[{"vns":i*1_000_000,"codes":values(v)}
                 for i,v in enumerate(ids)]
            x=rank_motion_diagnostic(rec)
            self.assertFalse(x["diagnostic_consistent_rank_sequence_candidate_only"])
            self.assertFalse(x["motor_rearm_permitted"])
        ties=[{"vns":i*1_000_000,"codes":[2048,2048,2049]}
              for i in range(60)]
        x=rank_motion_diagnostic(ties)
        self.assertEqual(x["rank_samples_with_ambiguous_ties"],60)
        self.assertEqual(x["distinct_state_observations"],0)
        with self.assertRaisesRegex(ValueError,"Unsafe"):
            rank_motion_diagnostic(ties,separation=1)

    def test_sparse_three_transitions_cannot_fake_direction_confidence(self):
        # Replicates the genuine KV147 end-of-300ms-coast hazard:
        # three apparent adjacent rank transitions but 95/100 tied codes.
        def ranked(state):
            order=RANK_SEQUENCE[state]
            out=[0,0,0]
            for i,p in enumerate(order):
                out[p]=[2100,2050,2000][i]
            return out
        rec=[]
        ranked_at={0:0,20:5,40:4,60:3,80:2}
        for i in range(100):
            rec.append({"vns":i*1_000_000,
                        "codes":ranked(ranked_at[i]) if i in ranked_at else
                                 [2048,2049,2048]})
        result=rank_motion_diagnostic(rec)
        self.assertEqual(result["rank_samples_with_ambiguous_ties"],95)
        self.assertGreaterEqual(result["adjacent_other_way_steps"],3)
        self.assertFalse(result["rank_coverage_sufficient"])
        self.assertFalse(result["rank_freshness_sufficient"])
        self.assertFalse(result["diagnostic_consistent_rank_sequence_candidate_only"])
        self.assertFalse(result["motor_rearm_permitted"])

    def test_versioned_profile_cannot_lower_sparse_or_stale_qualification(self):
        original=load_rank_profile()
        self.assertEqual(original["minimum_valid_rank_fraction"],0.75)
        for key,value in (("minimum_valid_rank_fraction",0.05),
                          ("maximum_valid_rank_sample_gap_ms",100),
                          ("minimum_one_way_rank_transitions",1),
                          ("rearm_permitted",True)):
            d=dict(original)
            d[key]=value
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/"bad.json"
                path.write_text(json.dumps(d))
                with self.assertRaisesRegex(ValueError,"Unsafe"):
                    load_rank_profile(path)

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
