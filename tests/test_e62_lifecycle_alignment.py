"""UNIT fixtures only: not motor, firmware-state, or hardware evidence."""
import unittest
from tests.test_e62_acquisition_timeline import fixture
from tools.e62_acquisition_timeline import analyze
from tools.e62_lifecycle_alignment import align


class LifecycleTests(unittest.TestCase):
    def test_audio_started_before_demand_remains_visible_without_new_write(self):
        events, scenario, meta = fixture()
        report = align(events, analyze(events, scenario, meta))
        self.assertEqual(report['stages'][1]['inferred_state'], 'AUDIO_CLOCK_CANDIDATE_OVERLAP')
        self.assertTrue(report['audio_intervals'][0]['right_censored'])
        self.assertFalse(report['guest_audio_owner_directly_observed'])

    def test_audio_exit_prevents_later_overlap_but_never_proves_owner_release(self):
        events, scenario, meta = fixture()
        index = next(i for i,e in enumerate(events) if e['kind']=='DSHOT' and e['data'][0]==2)
        events.insert(index, dict(seq=0,vns=events[index]['vns'],kind='PWM_TBCTL',data=[20,4,0,100000000,0,0]))
        for i,e in enumerate(events): e['seq']=i+1
        r=align(events,analyze(events,scenario,meta))
        self.assertFalse(r['stages'][1]['audio_candidate_intervals'])
        self.assertFalse(r['stages'][1]['audio_exclusion_proven'])
        self.assertFalse(r['audio_intervals'][0]['right_censored'])

    def test_no_clock_events_cannot_be_invented_from_dshot_or_switches(self):
        events, scenario, meta = fixture()
        events=[e for e in events if e['kind']!='PWM_TBCTL']
        r=align(events,analyze(events,scenario,meta))
        self.assertEqual(r['audio_intervals'],[])
        self.assertEqual(r['stages'][1]['inferred_state'],'NOT_OBSERVABLE')
        self.assertFalse(r['p1_qualified'])

    def test_full_overlay_keeps_absolute_timestamp_sequence_and_sampled_states(self):
        events, scenario, meta = fixture()
        r=align(events,analyze(events,scenario,meta))
        self.assertEqual(r['overlay'][0]['vns'],9000000)
        self.assertEqual(r['overlay'][0]['relative_ns'],-1000000)
        self.assertEqual(r['stages'][1]['boundary_state']['rotor_age_ns'],100)
        self.assertEqual(r['stages'][0]['boundary_state']['rotor_before']['rpm'],-6.066)
        self.assertFalse(r['hardware_qualified'])


if __name__=='__main__':unittest.main()
