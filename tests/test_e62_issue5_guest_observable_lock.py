import unittest
from tools.e62_issue5_guest_observable_lock import Observation,GuestObservableGuard,Decision

def obs(t,phase=0,sector=0,transition=0,level=1):
    return Observation(t,phase,sector,transition,level)

class GuestOnlyTests(unittest.TestCase):
    def test_one_phase_repeated_alias_cannot_become_reacquisition(self):
        g=GuestObservableGuard()
        self.assertEqual(g.offer(obs(2_600_000)),Decision.HOLD_UNQUALIFIED)
        self.assertEqual(g.offer(obs(12_400_000)),Decision.HOLD_UNQUALIFIED)
        self.assertEqual(g.offer(obs(23_700_000)),Decision.HOLD_UNQUALIFIED)

    def test_actual_distinct_sectors_still_only_handoff_review(self):
        g=GuestObservableGuard()
        self.assertEqual(g.offer(obs(2_000_000,0,0,1_000_000)),Decision.HOLD_UNQUALIFIED)
        self.assertEqual(g.offer(obs(5_000_000,1,1,3_000_000)),Decision.PROVISIONAL_SEQUENCE)
        self.assertEqual(g.offer(obs(8_000_000,2,2,6_000_000)),
                         Decision.EVIDENCE_SUFFICIENT_FOR_HANDOFF_REVIEW)

    def test_phase_sequence_reverse_rejected(self):
        g=GuestObservableGuard()
        self.assertEqual(g.offer(obs(2_000_000,0,0,1_000_000)),Decision.HOLD_UNQUALIFIED)
        self.assertEqual(g.offer(obs(5_000_000,2,5,3_000_000)),Decision.REJECT_INVALID)

    def test_invalid_and_stale_fail_closed(self):
        g=GuestObservableGuard()
        self.assertEqual(g.offer(obs(100_000)),Decision.HOLD_UNQUALIFIED)
        self.assertEqual(g.offer(obs(100_000)),Decision.REJECT_INVALID)
        self.assertEqual(g.offer(obs(400_000,1,1,200_000)),Decision.REJECT_INVALID)

    def test_same_guest_observations_can_have_different_hidden_rotor_causes(self):
        # No controller can infer speed-zero versus geometric-zero solely
        # from two byte-identical comparator/timer observations.
        genuine=GuestObservableGuard();alias=GuestObservableGuard()
        sequence=[obs(2_600_000),obs(12_400_000),obs(23_700_000)]
        actual_genuine_rotor_causes=["ANGLE","ANGLE","ANGLE"]
        actual_alias_rotor_causes=["ANGLE","SPEED","SPEED"]
        self.assertNotEqual(actual_genuine_rotor_causes,actual_alias_rotor_causes)
        self.assertEqual([genuine.offer(e) for e in sequence],
                         [alias.offer(e) for e in sequence])
        self.assertEqual(genuine.events,alias.events)

if __name__=="__main__":
    unittest.main()
