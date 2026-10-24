#!/usr/bin/env python3
"""Host-only compiler/virtual-clock sender contract (not firmware PASS)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.functional_dshot_scenario import (
    ScenarioError, load_scenario, percent_to_dshot, VirtualTimeDShotSequencer)

PLAN = Path(__file__).resolve().parents[1] / 'scenarios/e62-dshot-v1.json'


class FunctionalDShotScenarioTests(unittest.TestCase):
    def test_t01_exact_ramp_hold_and_boundaries(self):
        s = load_scenario(PLAN, 'T01')
        self.assertEqual((s.duration_ns, s.total_frames), (11_000_000_000, 11000))
        for ms, want in ((0,0), (10,66), (500,948), (990,1829),
                         (1000,1847), (10999,1847)):
            # The independent percent-to-DShot formula is the oracle.
            got = s.frame(ms)
            pct = (90*ms/1000) if ms < 1000 else 90
            self.assertEqual(got.dshot_value, percent_to_dshot(pct))
        self.assertEqual(s.frame(999).stage_index, 0)
        self.assertEqual(s.frame(1000).stage_index, 1)
        self.assertEqual(s.frame(999).pct, s.frame(990).pct)
        self.assertEqual(s.frame(10999).pct, 90)
        with self.assertRaises(ScenarioError):
            s.frame(11000)

    def test_t02_exact_eleven_10s_steps(self):
        s = load_scenario(PLAN, 'T02')
        self.assertEqual((s.duration_ns, s.total_frames), (110_000_000_000, 110000))
        for step in range(11):
            self.assertEqual(s.frame(step*10000).pct, step*10)
            self.assertEqual(s.frame(step*10000+9999).pct, step*10)
        self.assertEqual(s.frame(109999).dshot_value, 2047)

    def test_dshot_range_and_zero(self):
        self.assertEqual(percent_to_dshot(0), 0)
        self.assertEqual(percent_to_dshot(90), 1847)
        self.assertEqual(percent_to_dshot(100), 2047)
        self.assertEqual(percent_to_dshot('0.0001'), 48)
        for invalid in (-1, 101, float('nan'), True, 'wrong'):
            with self.assertRaises(ScenarioError):
                percent_to_dshot(invalid)

    def test_sequencer_guest_time_not_host_sleep(self):
        scenario = load_scenario(PLAN, 'T01')
        sent = []
        engine = VirtualTimeDShotSequencer(scenario, sent.append)
        self.assertIsNotNone(engine.poll(0))
        self.assertIsNone(engine.poll(100_000))
        self.assertIsNotNone(engine.poll(1_100_000))
        self.assertEqual(sent, [0, 0])
        with self.assertRaises(ScenarioError):
            engine.poll(3_100_000)  # frame at 2ms was missed
        self.assertEqual(engine.next_index, 2)
        self.assertEqual(len(sent), 2)

    def test_sequencer_does_not_advance_on_sender_error(self):
        scenario = load_scenario(PLAN, 'T01')
        def reject(_):
            raise RuntimeError('PA26 receiver busy')
        engine = VirtualTimeDShotSequencer(scenario, reject)
        with self.assertRaisesRegex(RuntimeError, 'busy'):
            engine.poll(0)
        self.assertEqual(engine.next_index, 0)

    def test_invalid_scenario_fail_closed(self):
        base = json.loads(PLAN.read_text())
        edits = (
            lambda d: d['target'].update(target_elf_sha256='bad'),
            lambda d: d['clock'].update(host_sleep_driven=True),
            lambda d: d['dshot'].update(protocol='DSHOT150'),
            lambda d: d['scenarios'][0]['stages'][0].update(update_period_ms=7.5),
            lambda d: d['scenarios'][0].update(expected_test_duration_s=12),
        )
        for edit in edits:
            data = json.loads(json.dumps(base))
            edit(data)
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp)/'invalid.json'
                p.write_text(json.dumps(data))
                with self.subTest(edit=edit), self.assertRaises(ScenarioError):
                    load_scenario(p, 'T01')


if __name__ == '__main__':
    unittest.main(verbosity=2)
