#!/usr/bin/env python3
"""Offline SIM_ONLY source chronology for issues #4/#5/#10; never controls QEMU."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.native_p0_strict import EVENT, KINDS, TraceError
from tools.native_p1_qualification import commands_for_scenario
from tools.e62_issue5_cap1_timer_audit import classify

ORIGINAL = '05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0'
PRODUCTION = 'c49a7485af218966a2e3ec764de8d997d8ba478954dcad42b88c0c99e4f3c003'
OBSERVER_KINDS = {'PWM_TBCTL', 'PWM_AUDIO_PERIOD', 'ADC_PHASE_EOC', 'ADC_PHASE_READ', 'ADC_VBUS_EOC'}


def read_events(lines):
    """Preserve raw sequence order, including equal-timestamp events."""
    rows = []
    for line in lines:
        if 'E62_P0_EVENT ' not in line:
            continue
        m = EVENT.search(line)
        if not m:
            raise TraceError('Malformed source event')
        seq, ns, kind = int(m[1]), int(m[2]), m[3]
        if len(rows) >= 200000:
            raise TraceError('Event budget exceeded; incomplete source')
        if kind not in KINDS | OBSERVER_KINDS or ns < 0:
            raise TraceError('Unknown event or invalid time')
        if seq != len(rows) + 1 or (rows and ns < rows[-1]['vns']):
            raise TraceError('Missing/reordered sequence or clock reversal')
        rows.append(dict(seq=seq, vns=ns, kind=kind,
                         data=[int(m[i]) for i in range(4, 10)]))
    if not rows:
        raise TraceError('No source events')
    return rows


def identity(meta):
    sha, family = meta['elf_sha256'], meta['firmware_class']
    expected = {ORIGINAL: 'original_rel17_3', PRODUCTION: 'production_root_fixes'}
    if family not in {'original_rel17_3', 'production_root_fixes', 'experimental_candidate'}:
        raise ValueError('Unknown firmware class')
    if expected.get(sha, 'experimental_candidate') != family:
        raise ValueError('Firmware identity/class mismatch')
    for key in ('elf_sha256', 'qemu_sha256', 'cfg_sha256', 'scenario_sha256'):
        v = meta[key]
        if len(v) != 64 or any(c not in '0123456789abcdef' for c in v):
            raise ValueError('Invalid SHA256: ' + key)
    for key in ('qemu_commit', 'firmware_commit', 'profile_id'):
        if not isinstance(meta[key], str) or not meta[key]:
            raise ValueError('Missing provenance: ' + key)
    if not isinstance(meta.get('effective_parameters'), dict) or not meta['effective_parameters']:
        raise ValueError('Effective model readback required')
    if meta.get('timebase') != 'QEMU_CLOCK_VIRTUAL':
        raise ValueError('Source virtual time required')
    if meta.get('host_guest_register_writes') is not False:
        raise ValueError('No-injection provenance required')
    if not isinstance(meta.get('experiment_contract'), dict) or not meta['experiment_contract']:
        raise ValueError('Explicit clock/BEMF/noise/runtime contract required')
    for key in ('rotor_max_age_ns', 'switch_max_age_ns'):
        if type(meta[key]) is not int or meta[key] <= 0:
            raise ValueError('Explicit positive diagnostic freshness budget required')


def rotor(e, boundary):
    if e is None:
        return None
    a = e['data']
    return dict(seq=e['seq'], vns=e['vns'], offset_ns=e['vns'] - boundary,
                rpm=a[0]/1000, electrical_angle_unwrapped_rad=a[1]/1000,
                electrical_angle_deg=math.degrees(a[1]/1000) % 360,
                currents_a=[v/1000 for v in a[2:5]], torque_nm=a[5]/1e6,
                provenance='source_observed_model_state')


def analyze(events, scenario, meta):
    identity(meta)
    if (scenario.get('schema') != 'e62.native.dshot.v1' or
        scenario.get('protocol') != 'DSHOT600' or
        scenario.get('frame_period_ns') != 1_000_000 or
        scenario.get('guest_ready_gating') is not False):
        raise ValueError('Unsupported source DShot scenario')
    stages = scenario['stages']
    if not stages or any(s.get('kind') != 'hold' or
        type(s.get('duration_ms')) is not int or s['duration_ms'] <= 0 or
        type(s.get('permille')) is not int or not 0 <= s['permille'] <= 1000
        for s in stages):
        raise ValueError('Positive-duration hold stages required')
    expected = list(commands_for_scenario([
        (s['duration_ms'], s['permille'], s['permille'], 1) for s in stages]))
    ds = [e for e in events if e['kind'] == 'DSHOT']
    if len(ds) != len(expected):
        raise ValueError('Incomplete DShot frame source')
    epoch = ds[1]['vns'] - 1_000_000 if len(ds) > 1 else ds[0]['vns']
    dispatch = []
    for i, (e, (stage, command)) in enumerate(zip(ds, expected)):
        if e['data'][:3] != [i, stage, command]:
            raise ValueError('DShot frame/stage/encoded command mismatch')
        late = e['vns'] - (epoch + i*1_000_000)
        dispatch.append(late)
        # Same dispatch contract as native_p1_qualification.analyze; no P1 change.
        if not 0 <= late <= (970000 if i == 0 else 100):
            raise ValueError('DShot cadence mismatch')
    boundaries = []
    first_rotor = next((e for e in events if e['kind'] == 'ROTOR'), None)
    index = 0
    for stage, spec in enumerate(stages):
        anchor = ds[index]
        # Ordering matters when a boundary shares a timestamp with a source event.
        prior = [e for e in events if e['seq'] < anchor['seq']]
        after = [e for e in events if e['seq'] >= anchor['seq']]
        r = next((e for e in reversed(prior) if e['kind'] == 'ROTOR'), None)
        rnext = next((e for e in after if e['kind'] == 'ROTOR'), None)
        switch = next((e for e in reversed(prior)
                       if e['kind'] in {'SWITCH', 'SWITCH_FOCUS'}), None)
        mode = next((e for e in reversed(prior) if e['kind'] == 'PWM_TBCTL'), None)
        age = None if r is None else anchor['vns']-r['vns']
        switch_age = None if switch is None else anchor['vns']-switch['vns']
        boundaries.append(dict(stage=stage, command_permille=spec['permille'],
            frame_index=index, seq=anchor['seq'], vns=anchor['vns'],
            relative_ns=anchor['vns']-ds[0]['vns'],
            rotor_before=rotor(r, anchor['vns']), rotor_after=rotor(rnext, anchor['vns']),
            rotor_age_ns=age,
            rotor_status='INCOMPLETE' if age is None or age > meta['rotor_max_age_ns'] else 'OBSERVED',
            observed_rotor_origin=rotor(first_rotor, anchor['vns']),
            electrical_displacement_from_first_sample_rad=None if r is None or first_rotor is None else (r['data'][1]-first_rotor['data'][1])/1000,
            switch_before=switch, switch_age_ns=switch_age,
            gate_active=None if switch_age is None or switch_age > meta['switch_max_age_ns'] else bool(switch['data'][1]),
            pwm_pad_mask=None if switch_age is None or switch_age > meta['switch_max_age_ns'] else switch['data'][0] & 63,
            switch_status='INCOMPLETE' if switch_age is None or switch_age > meta['switch_max_age_ns'] else 'OBSERVED',
            clock_before=mode,
            lifecycle='audio_candidate' if mode and ((mode['data'][1] >> 2) & 15) == 5 else 'not_observable',
            lifecycle_provenance='firmware_inferred' if mode else 'not_observable'))
        index += spec['duration_ms']
    stage_events = []
    for i, boundary in enumerate(boundaries):
        end_seq = boundaries[i+1]['seq'] if i+1 < len(boundaries) else events[-1]['seq']+1
        window = [e for e in events if boundary['seq'] <= e['seq'] < end_seq]
        kinds = ('PWM_PAIR', 'CMP_FILTER', 'CAP1', 'CAP1_ACK', 'ECAP1_CAP1_READ',
                 'T12_LOAD', 'T12_START', 'TIMG12', 'TIMG12_ACK')
        cmp = next((e for e in window if e['kind'] == 'CMP_FILTER'), None)
        stage_events.append(dict(stage=i,
            first_comparator=None if cmp is None else dict(
                seq=cmp['seq'], vns=cmp['vns'], mux_phase_index=cmp['data'][0],
                filtered_level=cmp['data'][1], phase_code=cmp['data'][2],
                active_dac_code=cmp['data'][3], polarity='NOT_OBSERVABLE',
                publication_identity='NOT_OBSERVABLE'),
            first_events={k: next((e for e in window if e['kind'] == k), None) for k in kinds},
            first_negative_sample=next((rotor(e, boundary['vns']) for e in window
                if e['kind'] == 'ROTOR' and e['data'][0] < 0), None),
            last_recorded_vns=window[-1]['vns'] if window else None))
    # Correlate complete capture windows only. The last capture is right-censored.
    captures = [e for e in events if e['kind'] == 'CAP1']
    flat = [dict(seq=e['seq'], vns=e['vns'], kind=e['kind'],
                 **dict(zip('abcdef', e['data']))) for e in events]
    chain = classify(flat, events[0]['vns'], events[-1]['vns'])
    if chain:
        chain[-1]['classification'] = 'INCOMPLETE_RIGHT_CENSORED'
    return dict(schema='e62.acquisition-timeline.v1', provenance=meta,
        source_status='VALID', dshot_dispatch_lateness_ns=dispatch, boundaries=boundaries, stage_events=stage_events, cap1_windows=chain,
        cap1_count=len(captures),
        reference_acquisition_status='INCOMPLETE_NOT_EXPOSED_IN_SOURCE_EVENT_SCHEMA',
        reference_limit='No ADC sample identity/epoch or active DAC publication proof in these event types',
        switch_limit_observed=any(e['kind'] == 'SWITCH_FOCUS_LIMIT' for e in events),
        first_start_verdict='NOT_QUALIFIED', flying_restart_verdict='NOT_QUALIFIED',
        p1_qualified=False, hardware_qualified=False)


def compare(a, b, meta_a, meta_b):
    """Earliest exact event mismatch, never a causal or P1 verdict."""
    for key in ('elf_sha256', 'firmware_class', 'qemu_sha256', 'cfg_sha256',
                'scenario_sha256', 'profile_id', 'effective_parameters', 'experiment_contract',
                'firmware_commit', 'qemu_commit'):
        if key not in meta_a or meta_a.get(key) != meta_b.get(key):
            raise ValueError('Unmatched experiment: ' + key)
    origins = [next(e['vns'] for e in rows if e['kind'] == 'DSHOT') for rows in (a, b)]
    def signature(e, origin):
        return (e['vns']-origin, e['kind'], e['data'])
    for i in range(max(len(a), len(b))):
        ea = a[i] if i < len(a) else None
        eb = b[i] if i < len(b) else None
        if ea is None or eb is None or signature(ea, origins[0]) != signature(eb, origins[1]):
            return dict(status='SOURCE_DIVERGENCE', index=i, a=ea, b=eb,
                        causal_attribution='NOT_ESTABLISHED')
    return dict(status='IDENTICAL_RECORDED_EVENTS', causal_attribution='NOT_ESTABLISHED')


def load(manifest):
    meta = json.loads(manifest.read_text())
    if not isinstance(meta, dict):
        raise ValueError('Manifest must be an object')
    identity(meta)
    files = {}
    for key in ('events', 'scenario', 'cfg', 'elf', 'qemu', 'evidence'):
        path = manifest.parent / meta['files'][key]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != meta[key + '_sha256']:
            raise ValueError('SHA mismatch: ' + key)
        files[key] = path
    evidence = json.loads(files['evidence'].read_text())
    if not isinstance(evidence, dict):
        raise ValueError('Run evidence must be an object')
    if (evidence.get('original_elf_sha256') != meta['elf_sha256'] or
        evidence.get('host_guest_register_writes') is not False or
        evidence.get('synthetic_timed_bemf_enabled') is not False or
        evidence.get('used_guest_wfi_or_gdb') is not False):
        raise ValueError('Run evidence identity or no-injection mismatch')
    effective = evidence.get('effective_sim_profile', {})
    if not isinstance(effective, dict):
        raise ValueError('Effective profile must be an object')
    if (effective.get('name') != meta['profile_id'] or
        effective.get('effective_parameters') != meta['effective_parameters'] or
        effective.get('checked_against_named_model') is not True):
        raise ValueError('Effective model readback mismatch')
    if evidence.get('native_dshot_scenario', {}).get('sha256') != meta['scenario_sha256']:
        raise ValueError('Run evidence scenario mismatch')
    events = read_events(files['events'].read_text().splitlines())
    if evidence.get('p0_source_event_count') != len(events):
        raise ValueError('Run evidence source count mismatch')
    sent = sum(e['kind'] == 'DSHOT' for e in events)
    if (evidence.get('configured_dshot_frames') != sent or
        evidence.get('autonomous_dshot', {}).get('sent') != sent):
        raise ValueError('Run evidence DShot count mismatch')
    scenario = json.loads(files['scenario'].read_text())
    if not isinstance(scenario, dict):
        raise ValueError('Scenario must be an object')
    result = analyze(events, scenario, meta)
    return events, meta, result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=Path)
    p.add_argument('--compare', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        events, meta, result = load(args.manifest)
        if args.compare:
            other, other_meta, _ = load(args.compare)
            result['comparison'] = compare(events, other, meta, other_meta)
        code = 0
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        result = dict(schema='e62.acquisition-timeline.v1', source_status='INCOMPLETE',
                      error=str(exc), p1_qualified=False, hardware_qualified=False)
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
