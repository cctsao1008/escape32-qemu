"""G13B7.1 original Guest T01 independent strict functional evidence gate.

This is a simulator-only sampled-stage policy. A 50-frame smoke or
a T02/other artifact must never satisfy this T01 gate. The original
Guest per-WFI fields stay NOT_MEASURED (null), not invented zeroes.
"""
import json
from pathlib import Path
import sys

EXPECTED_FRAMES = (1000, 11000)
GUEST_NS = 11_000_000_000

def validate(record):
    errors = []
    if record.get('status') != 'PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL':
        errors.append('aggregate_not_pass')
    if record.get('issues') != []:
        errors.append('unresolved_or_missing_oracle_issues')
    if record.get('dshot_frames_sent') != EXPECTED_FRAMES[-1]:
        errors.append('expected_11000_dshot_frames')
    if record.get('last_guest_virtual_elapsed_ns') != GUEST_NS:
        errors.append('expected_exact_11s_guest_virtual_time')

    stages = record.get('stages', [])
    autonomous = record.get('autonomous') or {}
    checkpoints = autonomous.get('stage_physical_checkpoints', [])
    if len(stages) != 2 or len(checkpoints) != 2:
        errors.append('expected_two_complete_ramp_hold_stages')
    for idx, count in enumerate(EXPECTED_FRAMES):
        if idx >= len(stages) or idx >= len(checkpoints):
            break
        stage, cp = stages[idx], checkpoints[idx]
        if cp.get('valid') is not True or cp.get('complete') is not True:
            errors.append(f'stage_{idx}_physical_checkpoint_not_qualified')
        if cp.get('index') != idx or cp.get('end_sent_cumulative') != count:
            errors.append(f'stage_{idx}_wire_count_or_index_mismatch')
        if (stage.get('sampled_stage_gate') or {}).get('status') != (
                'PASS_SAMPLED_STAGE_DIAGNOSTIC'):
            errors.append(f'stage_{idx}_sampled_gate_not_pass')
        for field in ('valid_crc_feeds_observed', 'native_steps_observed'):
            if field not in stage or stage[field] is not None:
                errors.append(f'stage_{idx}_{field}_must_be_not_measured_null')

    timing = autonomous.get('event_timing_evidence') or {}
    if not isinstance(timing.get('trace_triplets'), int) or (
            timing['trace_triplets'] <= 0):
        errors.append('missing_bemf_cap1_timg12_temporal_associations')
    if (autonomous.get('neutral_teardown') or {}).get('qualified') is not True:
        errors.append('source_owned_neutral_teardown_not_qualified')
    return errors

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('artifact',type=Path)
    ap.add_argument('--output',type=Path)
    args=ap.parse_args()
    result=validate(json.loads(args.artifact.read_text(encoding='utf-8')))
    report={
        'status':'PASS_T01_STRICT_FUNCTIONAL_ONLY' if not result
                 else 'FAIL_T01_FUNCTIONAL_EVIDENCE',
        'issues':result,
        'scope':'G13B7_1_ORIGINAL_GUEST_SCRIPTED_BEMF_SAMPLE_AND_PHYSICAL_WIRE',
        'rotor_order':'OPEN_NOT_PROVEN',
        'board_or_thermal_safety':'NOT_QUALIFIED'
    }
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('E62_T01_INDEPENDENT_QUALIFICATION '+json.dumps(report,sort_keys=True))
    return 1 if result else 0

if __name__=='__main__':sys.exit(main())
