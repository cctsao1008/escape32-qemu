#!/usr/bin/env python3
"""E62 Issue #5 read-only sweep re-analysis with event-driven Gate dwell.

Uses existing QEMU artifacts. Never launches QEMU, rewrites Guest ELF/CFG,
changes motor plant, or modifies source tests. Re-analysis results are
written to a separate versioned report directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from statistics import median

ELF_SHA = 'c49a7485af218966a2e3ec764de8d997d8ba478954dcad42b88c0c99e4f3c003'
CFG_SHA = '77366cfe9f0632b795a72393f7f0e990a99e8af92429cbb82d42bbb3f7c8ed4b'
COASTS = (20, 100, 300)
ANGLES = (-90, -30, 0, 90)
EVENT = re.compile(r'\bvns=(\d+)\s+kind=(\w+)(?:\s+a=(-?\d+))?(?:\s+b=(-?\d+))?')
MS = 1_000_000


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def window(values, lo, hi):
    return [v for t, v in values if lo <= t < hi]


def read_source(path, start, drive_end):
    rpms, focus, limits = [], [], []
    last_ns = 0
    begin_ns, end_ns = (start - 5) * MS, (start + 40) * MS
    with path.open(encoding='utf-8', errors='replace') as f:
        for line in f:
            m = EVENT.search(line)
            if not m:
                continue
            ns, kind, a, b = m.groups()
            ns = int(ns)
            last_ns = max(last_ns, ns)
            if kind == 'ROTOR' and (start - 250) * MS <= ns <= drive_end * MS and a is not None:
                rpms.append((ns / MS, int(a) / 1000.0))
            elif kind == 'SWITCH_FOCUS' and begin_ns <= ns <= end_ns and a is not None and b is not None:
                focus.append((ns, int(a), int(b)))
            elif kind == 'SWITCH_FOCUS_LIMIT' and begin_ns <= ns <= end_ns:
                limits.append(ns)
    return rpms, focus, limits, last_ns


def classify(mask, gate):
    effective = mask if gate else 0
    hi = sum(bool(effective & (1 << i)) for i in (0, 2, 4))
    lo = sum(bool(effective & (1 << i)) for i in (1, 3, 5))
    return ('ALL_OFF' if effective == 0 else
            'LOW_SIDE_SHORT' if hi == 0 and lo >= 2 else 'OTHER')


def gate_dwell(focus, limits, start, last_source_ns, observation_end_ms=None):
    """Step-function reconstruction from QEMU transition-only source.

    Require an event at/before coast onset to seed state, full configured
    observation window 2995..3040ms, an event source still running after
    that window, and no focus event budget exhaustion. The absence of a new
    transition is a hold of the most recent mask, not missing coverage.
    """
    lo, hi = start * MS, (start + 20) * MS
    observation_end_ms = start + 40 if observation_end_ms is None else observation_end_ms
    items = sorted(focus)
    reasons = []
    if not items:
        reasons.append('NO_FOCUS_EVENTS')
    if limits:
        reasons.append('FOCUS_RECORD_BUDGET_EXHAUSTED')
    if observation_end_ms * MS <= hi:
        reasons.append('FOCUS_OBSERVATION_WINDOW_TOO_SHORT')
    if last_source_ns <= observation_end_ms * MS:
        reasons.append('NO_SOURCE_EVENTS_AFTER_FOCUS_WINDOW')
    seeds = [e for e in items if e[0] <= lo]
    if not seeds:
        reasons.append('NO_GATE_STATE_AT_COAST_START')
    if any(items[i][0] > items[i+1][0] for i in range(len(items)-1)):
        reasons.append('UNSORTED_SOURCE')

    dwell = {'ALL_OFF': 0, 'LOW_SIDE_SHORT': 0, 'OTHER': 0}
    if reasons:
        return dict(status='INCOMPLETE', reasons=reasons, covered_ns=0,
                    coverage_percent=0, percent=None, observed_dwell_ns=dwell,
                    focus_events=len(items), focus_limit_events=len(limits),
                    last_source_ns=last_source_ns)
    _, mask, gate = seeds[-1]
    previous = lo
    in_coast = 0
    for ns, next_mask, next_gate in items:
        if ns <= lo:
            continue
        if ns >= hi:
            break
        dwell[classify(mask, gate)] += ns - previous
        previous = ns
        mask, gate = next_mask, next_gate
        in_coast += 1
    dwell[classify(mask, gate)] += hi - previous
    total = sum(dwell.values())
    if total != hi - lo:
        raise AssertionError('Gate duration conservation failed')
    return dict(status='COMPLETE', reasons=[], covered_ns=total,
                coverage_percent=100.0,
                percent={k: round(v * 100.0 / total, 3) for k, v in dwell.items()},
                observed_dwell_ns=dwell,
                focus_events=len(items), focus_events_in_coast=in_coast,
                focus_limit_events=0,
                last_source_ns=last_source_ns,
                initial_state={'mask':seeds[-1][1], 'gate':seeds[-1][2]},
                final_state={'mask':mask, 'gate':gate},
                closing_policy='SOURCE_TRANSITION_STATE_HOLD')


def report_case(base, outdir, label, coast, angle):
    artifact = base / f'{label}.json'
    scenario = base / f'scenario-coast{coast:03d}.json'
    evlog = base / f'{label}.p0.events.log'
    for p in (artifact, scenario, evlog):
        if not p.is_file():
            return dict(case=label, availability='MISSING', missing=str(p),
                        overall_heuristic='NOT_EVALUATED')
    meta = json.loads(artifact.read_text())
    scenario_sha = (meta.get('native_dshot_scenario') or {}).get('sha256')
    if scenario_sha != sha(scenario):
        raise ValueError(f'{label} scenario SHA mismatch')
    if meta.get('original_elf_sha256') != ELF_SHA:
        raise ValueError(f'{label} ELF SHA mismatch')
    model = ((meta.get('motor_before') or {}).get('effective_sim_motor_model') or {})
    if model.get('configured_initial_electrical_mdeg') != angle * 1000:
        raise ValueError(f'{label} initial electrical angle mismatch')
    expected_focus = f'{3000 - 5}:{3000 + 40}'
    if meta.get('source_focus_window_ms') != expected_focus:
        raise ValueError(f'{label} focus window mismatch')
    s = json.loads(scenario.read_text())['stages']
    expected = [(1500, 0), (1500, 200), (coast, 0), (1500, 200), (300, 0)]
    if [(x['duration_ms'], x['permille']) for x in s] != expected:
        raise ValueError(f'{label} scenario stages mismatch')
    start, end, drive_end = 3000, 3000 + coast, 3000 + coast + 1500
    rpms, focus, limits, last_ns = read_source(evlog, start, drive_end)
    gate = gate_dwell(focus, limits, start, last_ns)
    before = window(rpms, start - 10, start)
    after = window(rpms, end - 2, end)
    demand1 = window(rpms, start - 200, start)
    steady = window(rpms, drive_end - 300, drive_end)
    drive = window(rpms, end + 50, drive_end)
    values = {
        'rpm_before_coast': round(before[-1], 3) if before else None,
        'rpm_end_coast': round(after[-1], 3) if after else None,
        'demand1_median_rpm': round(median(demand1), 3) if demand1 else None,
        'restart_last300_median_rpm': round(median(steady), 3) if steady else None,
        'restart_min_rpm_after50ms': round(min(drive), 3) if drive else None,
        'restart_max_rpm_after50ms': round(max(drive), 3) if drive else None,
    }
    source_complete = (meta.get('autonomous_dshot') or {}).get('sent') == (end + 1800)
    source_complete &= meta.get('configured_dshot_frames') == (end + 1800)
    source_complete &= (meta.get('native_motor') or {}).get('model_fault') == 0
    source_complete &= meta.get('wiring_failure_reasons') == []
    source_complete &= meta.get('receiver_failure_reasons') == []
    runtime_pass = source_complete and not meta.get('exception') and not str(meta.get('status','')).startswith('FAIL')
    coast_rpm_ok = bool(before and after and before[-1] > 100 and after[-1] > 0 and
                        after[-1] >= before[-1] * 0.70)
    gate_ok = gate['status'] == 'COMPLETE'
    coast_ok = gate_ok and coast_rpm_ok and gate['percent']['ALL_OFF'] >= 95 and gate['percent']['LOW_SIDE_SHORT'] <= 2
    restart_evaluable = bool(demand1 and steady and drive and median(demand1) > 100)
    restart_ok = restart_evaluable and min(steady) > 0 and min(drive) > 0 and (0.85 <= median(steady) / median(demand1) <= 1.15) and (max(steady)-min(steady)) / median(demand1) <= .20
    result = dict(
        case=label, availability='PRESENT', coast_ms=coast,
        initial_electrical_degrees=angle,
        host_probe_status=meta.get('status'), host_probe_exception=meta.get('exception'),
        model_fault=(meta.get('native_motor') or {}).get('model_fault'),
        dshot_sent=(meta.get('autonomous_dshot') or {}).get('sent'),
        dshot_expected=meta.get('configured_dshot_frames'),
        wiring_failure_reasons=meta.get('wiring_failure_reasons'),
        receiver_failure_reasons=meta.get('receiver_failure_reasons'),
        gate_first_20ms_trace=gate, gate_first_20ms_percent=gate['percent'],
        coast_rpm_heuristic='PASS' if coast_rpm_ok else 'FAIL_OR_INCONCLUSIVE',
        coast_heuristic='FAIL' if not coast_rpm_ok else ('INCONCLUSIVE_GATE_TRACE' if not gate_ok else 'PASS' if coast_ok else 'FAIL'),
        restart_heuristic='PASS' if restart_ok else ('FAIL' if restart_evaluable else 'INCONCLUSIVE'),
        runtime_integrity='PASS' if runtime_pass else 'FAIL',
        overall_heuristic='PASS' if coast_ok and restart_ok and runtime_pass else 'NOT_PASS',
        **values
    )
    (outdir / f'{label}.metrics.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',type=Path,nargs='?',default=Path.cwd())
    p.add_argument('--summarize',action='store_true',required=True)
    args=p.parse_args()
    root=args.root.expanduser().resolve()
    base=root/'artifacts/issue5/ztc-robustness'
    cfg=root/'artifacts/issue5/ztc-ab/B-ztc1-damp1.cfg.bin'
    if not cfg.is_file() or sha(cfg)!=CFG_SHA:
        raise SystemExit('Missing/mismatched reference ZTC CFG')
    if not base.is_dir():
        raise SystemExit(f'Missing artifacts directory: {base}')
    outdir=base/'analysis-v2'
    outdir.mkdir(exist_ok=True)
    rows=[]
    print('case                          coast  restart  runtime  RPM_d1  RPM_d2  off%  gate_trace')
    for coast in COASTS:
        for angle in ANGLES:
            label=f'coast{coast:03d}-angle{angle:+04d}'
            try:
                result=report_case(base,outdir,label,coast,angle)
            except (ValueError,KeyError,TypeError,IndexError,AssertionError) as exc:
                result=dict(case=label,availability='INVALID',error=f'{type(exc).__name__}: {exc}',overall_heuristic='NOT_EVALUATED')
            rows.append(result)
            print(f'{label:29} {result.get("coast_heuristic","N/A"):6} '
                  f'{result.get("restart_heuristic","N/A"):8} '
                  f'{result.get("runtime_integrity","N/A"):7} '
                  f'{str(result.get("demand1_median_rpm")):7} '
                  f'{str(result.get("restart_last300_median_rpm")):7} '
                  f'{str((result.get("gate_first_20ms_percent") or {}).get("ALL_OFF")):5} '
                  f'{(result.get("gate_first_20ms_trace") or {}).get("status","N/A")}')
    report=dict(schema='e62.issue5.ztc-robustness-analysis.v2',
                elf_sha256=ELF_SHA,cfg_sha256=CFG_SHA,
                cases_expected=12,cases_present=sum(x['availability']=='PRESENT' for x in rows),
                coast_pass_cases=sum(x.get('coast_heuristic')=='PASS' for x in rows),
                restart_pass_cases=sum(x.get('restart_heuristic')=='PASS' for x in rows),
                runtime_pass_cases=sum(x.get('runtime_integrity')=='PASS' for x in rows),
                overall_pass_cases=sum(x.get('overall_heuristic')=='PASS' for x in rows),
                meaning='Host heuristic A/B only, not Motor P1 or hardware qualification',
                cases=rows)
    result=outdir/'summary.json'
    result.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print('REPORT:',result)
    print('COUNTS:',json.dumps({k:v for k,v in report.items() if k.endswith('_cases') or k=='cases_present'},sort_keys=True))
    return 0 if report['cases_present']==12 else 2

if __name__=='__main__':
    raise SystemExit(main())
