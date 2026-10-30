"""Source-owned passive electrical phase rank is NOT a rotor angle sensor."""
import unittest
from test_e62_restart_phase_torque_audit import scenario, events as fixture
from tools.e62_passive_phase_order_alias_audit import audit,SECTOR_ORDER

def make_source(states):
    s=scenario(300)
    rows=fixture(s)
    t=next(e["vns"] for e in rows if
           e["kind"]=="DSHOT" and e["data"][0]==3000)
    for i in range(100):
        state=states[min(len(states)-1,i//10)]
        rank=SECTOR_ORDER[state]
        volts=[2048]*3
        volts[rank[0]]=2054
        volts[rank[1]]=2048
        volts[rank[2]]=2042
        rows.append({"kind":"BEMF_FRONTEND",
                     "vns":t+i*1_000_000+500_000,
                     "data":tuple(volts)+(0,2048,0)})
    return sorted(rows,key=lambda x:x["vns"]),s

class PassiveRank(unittest.TestCase):
    def test_adjacent_model_phase_sequence_still_not_authorized(self):
        e,s=make_source([0,5,4,3,2,1,0])
        r=audit(e,s)
        self.assertEqual(r["skipped_or_ambiguous_sector_transitions"],0)
        self.assertEqual(r["classification"],"NO_SKIPS_SEEN_STILL_UNQUALIFIED")
        self.assertFalse(r["native_guest_rearm_permitted"])
        self.assertFalse(r["qualified_physical_rotor_direction"])

    def test_skipped_rank_states_fail_closed(self):
        e,s=make_source([0,4,3,2,1,0])
        r=audit(e,s)
        self.assertEqual(r["classification"],"PHASE_SECTOR_SKIPS_UNOBSERVABLE")
        self.assertGreater(r["skipped_or_ambiguous_sector_transitions"],0)
        self.assertFalse(r["native_guest_rearm_permitted"])

    def test_missing_phase_samples_rejected(self):
        e,s=make_source([0,5,4,3,2,1])
        e=[v for v in e if v["kind"]!="BEMF_FRONTEND"]
        with self.assertRaisesRegex(ValueError,"Missing or duplicated"):
            audit(e,s)

    def test_adc_overflow_rejected(self):
        e,s=make_source([0,5,4,3,2,1])
        v=next(x for x in e if x["kind"]=="BEMF_FRONTEND")
        v["data"]=(4096,2048,2048,0,2048,0)
        with self.assertRaisesRegex(ValueError,"Invalid source phase"):
            audit(e,s)

    def test_dshot_frame_corruption_rejected(self):
        e,s=make_source([0,5,4,3,2,1])
        v=next(x for x in e if x["kind"]=="DSHOT" and x["data"][0]==3300)
        v["data"]=(3300,3,0,0,0,0)
        with self.assertRaisesRegex(ValueError,"DShot source"):
            audit(e,s)

    def test_no_invented_source_clock(self):
        e,s=make_source([0,5,4,3,2,1])
        v=next(x for x in e if x["kind"]=="DSHOT" and x["data"][0]==3300)
        v["vns"]+=1000
        with self.assertRaisesRegex(ValueError,"clock"):
            audit(sorted(e,key=lambda x:x["vns"]),s)

    def test_bad_coast_command_rejected(self):
        e,s=make_source([0,5,4,3,2,1])
        s["stages"][2]["permille"]=200
        with self.assertRaisesRegex(ValueError,"Unrecognized"):
            audit(e,s)

if __name__=="__main__":
    unittest.main()
