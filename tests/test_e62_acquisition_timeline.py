"""Synthetic UNIT source logs only: never firmware/motor qualification evidence."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.e62_acquisition_timeline import ORIGINAL, PRODUCTION, analyze, compare, identity, read_events, load
from tools.native_p0_strict import TraceError
from tools.native_p1_qualification import commands_for_scenario


def fixture():
    scenario = dict(schema='e62.native.dshot.v1', protocol='DSHOT600',
                    frame_period_ns=1000000, guest_ready_gating=False,
                    stages=[dict(kind='hold', duration_ms=n, permille=p)
                            for n, p in ((2, 0), (2, 200), (1, 0), (2, 200))])
    meta = dict(elf_sha256=ORIGINAL, firmware_class='original_rel17_3',
                qemu_sha256='a'*64, cfg_sha256='b'*64, scenario_sha256='c'*64,
                firmware_commit='firmware-pin', qemu_commit='qemu-pin',
                profile_id='UNIT_ONLY', effective_parameters={'vbus': 24},
                experiment_contract={'classification': 'UNIT_ONLY'},
                timebase='QEMU_CLOCK_VIRTUAL', host_guest_register_writes=False,
                rotor_max_age_ns=1000000, switch_max_age_ns=1000000)
    rows = []
    def event(ns, kind, data):
        rows.append(dict(seq=len(rows)+1, vns=ns, kind=kind, data=data))
    event(9000000, 'PWM_TBCTL', [0, 20, 100, 200000000, 1, 0])
    for i, (stage, cmd) in enumerate(commands_for_scenario([
        (s['duration_ms'], s['permille'], s['permille'], 1) for s in scenario['stages']])):
        ns = 10000000 + i*1000000
        event(ns-100, 'ROTOR', [-6066, -20116, 1, -2, 1, -100])
        event(ns-50, 'SWITCH', [24, 1, 0, 0, 0, 0])
        event(ns, 'DSHOT', [i, stage, cmd, 0, 0, 0])
    return rows, scenario, meta


class TimelineTests(unittest.TestCase):
    def test_boundary_uses_shifted_source_frame_and_preserves_sample_age(self):
        e, s, m = fixture()
        r = analyze(e, s, m)
        b = r['boundaries'][1]
        self.assertEqual((b['vns'], b['relative_ns'], b['rotor_age_ns']), (12000000, 2000000, 100))
        self.assertAlmostEqual(b['rotor_before']['rpm'], -6.066)
        self.assertEqual(b['rotor_before']['currents_a'], [.001, -.002, .001])
        self.assertEqual(b['lifecycle'], 'audio_candidate')  # carried across demand
        self.assertEqual(r['boundaries'][3]['frame_index'], 5)  # variable coast
        self.assertFalse(r['p1_qualified'])
        self.assertIn('INCOMPLETE', r['reference_acquisition_status'])

    def test_missing_rotor_and_switch_are_incomplete_not_zero(self):
        e, s, m = fixture()
        e = [r for r in e if r['kind'] not in ('ROTOR', 'SWITCH')]
        r = analyze(e, s, m)['boundaries'][1]
        self.assertIsNone(r['rotor_before'])
        self.assertEqual(r['switch_status'], 'INCOMPLETE')

    def test_stale_samples_do_not_confer_boundary_coverage(self):
        e, s, m = fixture()
        m['rotor_max_age_ns'] = 50
        m['switch_max_age_ns'] = 10
        b = analyze(e, s, m)['boundaries'][1]
        self.assertEqual(b['rotor_status'], 'INCOMPLETE')
        self.assertEqual(b['switch_status'], 'INCOMPLETE')

    def test_original_and_production_fixes_are_distinct(self):
        _, _, m = fixture()
        m['elf_sha256'] = PRODUCTION
        with self.assertRaises(ValueError): identity(m)
        m['firmware_class'] = 'production_root_fixes'
        identity(m)

    def test_missing_duplicate_wrong_encoded_commands_fail(self):
        for mutation in ('missing', 'duplicate', 'command', 'time'):
            with self.subTest(mutation=mutation):
                e, s, m = fixture()
                ds = [r for r in e if r['kind'] == 'DSHOT']
                if mutation == 'missing': e.remove(ds[-1])
                if mutation == 'duplicate': ds[-1]['data'][0] = 0
                if mutation == 'command': ds[2]['data'][2] = 200  # encoded != permille
                if mutation == 'time': ds[-1]['vns'] += 1000
                with self.assertRaises(ValueError): analyze(e, s, m)

    def test_source_vbus_observation_is_retained_without_calibration_claim(self):
        line='E62_P0_EVENT seq=1 vns=2 kind=ADC_VBUS_EOC a=1 b=1490 c=12 d=1 e=24000 f=0'
        e=read_events([line])[0]
        self.assertEqual(e['kind'],'ADC_VBUS_EOC')
        self.assertEqual(e['data'],[1,1490,12,1,24000,0])

    def test_parser_rejects_gap_reversal_malformed_and_unknown(self):
        base = 'E62_P0_EVENT seq={} vns={} kind={} a=0 b=0 c=0 d=0 e=0 f=0'
        for text in (base.format(2, 1, 'ROTOR'),
                     base.format(1, 2, 'ROTOR')+'\n'+base.format(2, 1, 'ROTOR'),
                     'E62_P0_EVENT broken', base.format(1, 1, 'INVENTED_CAP1')):
            with self.assertRaises(TraceError): read_events(text.splitlines())

    def test_comparison_detects_earliest_exact_divergence_and_mismatched_inputs(self):
        a, _, m = fixture()
        b = copy.deepcopy(a)
        b[4]['data'][0] += 1
        self.assertEqual(compare(a, b, m, m)['index'], 4)
        n = dict(m, cfg_sha256='d'*64)
        with self.assertRaises(ValueError): compare(a, b, m, n)

    def test_capture_tail_cannot_claim_complete_acquisition(self):
        e, s, m = fixture()
        e.append(dict(seq=len(e)+1, vns=e[-1]['vns']+1, kind='CAP1', data=[0]*6))
        r = analyze(e, s, m)
        self.assertEqual(r['cap1_windows'][-1]['classification'], 'INCOMPLETE_RIGHT_CENSORED')

    def test_manifest_binds_all_input_bytes_and_effective_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            e, scenario, meta = fixture()
            payloads = {'elf': b'UNIT_CANDIDATE_NOT_FIRMWARE', 'qemu': b'UNIT_NOT_EXECUTABLE',
                        'cfg': b'UNIT_NOT_BOARD_CALIBRATION',
                        'scenario': json.dumps(scenario).encode(),
                        'events': ('\n'.join('E62_P0_EVENT seq={seq} vns={vns} kind={kind} '.format(**r)+
                            ' '.join(f'{k}={v}' for k,v in zip('abcdef',r['data'])) for r in e)).encode()}
            meta['firmware_class'] = 'experimental_candidate'
            for k,v in payloads.items():
                meta[k+'_sha256'] = hashlib.sha256(v).hexdigest()
            evidence = dict(original_elf_sha256=meta['elf_sha256'], host_guest_register_writes=False,
                            synthetic_timed_bemf_enabled=False, used_guest_wfi_or_gdb=False,
                            effective_sim_profile=dict(name=meta['profile_id'],
                                effective_parameters=meta['effective_parameters'], checked_against_named_model=True),
                            native_dshot_scenario=dict(sha256=meta['scenario_sha256']),
                            p0_source_event_count=len(e), configured_dshot_frames=7,
                            autonomous_dshot=dict(sent=7))
            payloads['evidence'] = json.dumps(evidence).encode()
            meta['evidence_sha256'] = hashlib.sha256(payloads['evidence']).hexdigest()
            meta['files'] = {k:k for k in payloads}
            for k,v in payloads.items(): (root/k).write_bytes(v)
            manifest = root/'manifest.json'
            manifest.write_text(json.dumps(meta))
            self.assertEqual(load(manifest)[2]['source_status'], 'VALID')
            for key in payloads:
                with self.subTest(key=key):
                    (root/key).write_bytes(payloads[key]+b'tampered')
                    with self.assertRaisesRegex(ValueError, 'SHA mismatch'): load(manifest)
                    (root/key).write_bytes(payloads[key])
            meta['effective_parameters'] = {'vbus': 47}
            manifest.write_text(json.dumps(meta))
            with self.assertRaisesRegex(ValueError, 'readback mismatch'): load(manifest)

    def test_cli_missing_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'report.json'
            p = subprocess.run([sys.executable, 'tools/e62_acquisition_timeline.py',
                                str(Path(tmp)/'missing.json'), '--output', str(out)], capture_output=True)
            self.assertEqual(p.returncode, 1)
            self.assertEqual(json.loads(out.read_text())['source_status'], 'INCOMPLETE')


if __name__ == '__main__': unittest.main()
