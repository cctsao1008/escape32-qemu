#!/usr/bin/env python3
"""Read-only firmware lifecycle overlay; register proxies never prove ownership."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.e62_acquisition_timeline import load

OVERLAY = {'DSHOT', 'PWM_TBCTL', 'PWM_AUDIO_PERIOD', 'PWM_PAIR', 'SWITCH',
           'SWITCH_FOCUS', 'SWITCH_FOCUS_LIMIT', 'ROTOR', 'CMP_FILTER', 'CAP1',
           'CAP1_ACK', 'ECAP1_CAP1_READ', 'T12_LOAD', 'T12_START', 'T12_STOP',
           'TIMG12', 'TIMG12_ACK', 'ADC_PHASE_EOC', 'ADC_PHASE_READ', 'ADC_VBUS_EOC'}


def align(events, source):
    origin = next(e['vns'] for e in events if e['kind'] == 'DSHOT')
    intervals = []
    opened = None
    for e in events:
        if e['kind'] != 'PWM_TBCTL':
            continue
        div = (e['data'][1] >> 2) & 15
        if div == 5 and opened is None:
            opened = e
        if div != 5 and opened is not None:
            intervals.append(dict(begin=opened, end=e, right_censored=False))
            opened = None
    if opened is not None:
        intervals.append(dict(begin=opened, end=None, right_censored=True))
    stages = []
    boundaries = source['boundaries']
    for i, b in enumerate(boundaries):
        end = boundaries[i+1]['seq'] if i+1 < len(boundaries) else events[-1]['seq']+1
        rows = [e for e in events if b['seq'] <= e['seq'] < end]
        overlaps = [n for n, window in enumerate(intervals)
                    if window['begin']['seq'] < end and
                    (window['end'] is None or window['end']['seq'] >= b['seq'])]
        pair = next((e for e in rows if e['kind'] == 'PWM_PAIR'), None)
        positive = b['command_permille'] > 0
        # Candidate labels are deliberately distinct from software-private state.
        state = ('AUDIO_CLOCK_CANDIDATE_OVERLAP' if overlaps else
                 'DRIVE_CANDIDATE' if positive and pair else
                 'NEUTRAL_COMMAND_MOTOR_STATE_SEPARATE' if not positive else
                 'NOT_OBSERVABLE')
        stages.append(dict(stage=i, begin_vns=b['vns'],
            boundary_state=b, observed_through_vns=rows[-1]['vns'] if rows else None,
            external_command_permille=b['command_permille'],
            inferred_state=state, provenance='firmware_inferred',
            audio_candidate_intervals=overlaps,
            audio_exclusion_proven=False,
            gate_state_complete=b['switch_status'] == 'OBSERVED'))
    return dict(schema='e62.lifecycle-alignment.v1', timebase='QEMU_CLOCK_VIRTUAL',
        time_origin_vns=origin, firmware_class=source['provenance']['firmware_class'],
        provenance=source['provenance'],
        audio_intervals=intervals, guest_audio_owner_directly_observed=False,
        stages=stages,
        overlay=[dict(e, relative_ns=e['vns']-origin,
                      provenance='source_observed') for e in events if e['kind'] in OVERLAY],
        source_coverage='COMPLETE_RECORDED_STREAM_NOT_ALL_WAVEFORM_EDGES',
        lifecycle_verdict='INCOMPLETE_PRIVATE_STATES_INFERRED',
        reference_verdict=source['reference_acquisition_status'],
        p1_qualified=False, hardware_qualified=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    try:
        events, _, source = load(args.manifest)
        report = align(events, source)
        code = 0
    except (OSError, ValueError, TypeError, KeyError, StopIteration) as exc:
        report = dict(schema='e62.lifecycle-alignment.v1',
                      lifecycle_verdict='INCOMPLETE', error=str(exc),
                      p1_qualified=False, hardware_qualified=False)
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
