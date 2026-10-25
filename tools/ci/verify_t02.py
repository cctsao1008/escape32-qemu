"""Fail-closed T02 acceptance on original unaltered Rel17.3 Guest."""
import json
import sys

def validate(record):
    errors=[]
    stages=record.get('stages') or []
    autonomous=record.get('autonomous') or {}
    checks=autonomous.get('stage_physical_checkpoints') or []
    if record.get('status')!='PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL':
        errors.append('aggregate_not_pass')
    if record.get('issues')!=[]:
        errors.append('unresolved_or_missing_oracle_issues')
    if record.get('dshot_frames_sent')!=110000:
        errors.append('expected_110000_frames')
    if record.get('last_guest_virtual_elapsed_ns')!=110_000_000_000:
        errors.append('expected_exact_110s_guest_virtual_time')
    if record.get('completed_full_duration') is not True:
        errors.append('not_full_duration_guest')
    if len(stages)!=11 or len(checks)!=11:
        errors.append('requires_11_completed_stages')
    for idx in range(11):
        if idx>=len(stages) or idx>=len(checks): break
        cp=checks[idx]; stage=stages[idx]
        expected_sent=(idx+1)*10000
        if cp.get('valid') is not True or cp.get('complete') is not True:
            errors.append(f'stage_{idx}_checkpoint_incomplete')
        if cp.get('index')!=idx or cp.get('end_sent_cumulative')!=expected_sent:
            errors.append(f'stage_{idx}_sent_or_index_wrong')
        if (cp.get('declared_start_ms')!=idx*10000 or
            cp.get('declared_end_ms')!=expected_sent):
            errors.append(f'stage_{idx}_declared_boundary_mismatch')
        if (stage.get('index')!=idx or stage.get('kind')!='hold' or
            stage.get('to_pct')!=idx*10 or
            stage.get('frames_sent')!=10000):
            errors.append(f'stage_{idx}_plan_or_frame_coverage_wrong')
        if (stage.get('sampled_stage_gate') or {}).get('status') != (
                'PASS_SAMPLED_STAGE_DIAGNOSTIC'):
            errors.append(f'stage_{idx}_sampled_gate_not_pass')
        for legacy in ('valid_crc_feeds_observed','native_steps_observed'):
            if legacy not in stage or stage[legacy] is not None:
                errors.append(f'stage_{idx}_{legacy}_must_be_null_not_measured')
    evidence=autonomous.get('event_timing_evidence') or {}
    if (not isinstance(evidence.get('trace_triplets'),int) or
            evidence['trace_triplets']<=0):
        errors.append('no_qemu_temporal_cross_cap_timg12_triplets')
    if (autonomous.get('neutral_teardown') or {}).get('qualified') is not True:
        errors.append('source_owned_neutral_teardown_not_qualified')
    return errors

def main():
    d=json.load(open(sys.argv[1],encoding='utf-8'))
    errors=validate(d)
    print('E62_T02_INDEPENDENT_QUALIFICATION '+json.dumps({
        'status':'PASS' if not errors else 'FAIL',
        'issues':errors,'scope':'FUNCTIONAL_SCRIPTED_BEMF_NOT_PHYSICAL_MOTOR',
        'stage_count':len(d.get('stages',[])),'frames':d.get('dshot_frames_sent')
    },sort_keys=True),flush=True)
    return 1 if errors else 0

if __name__=='__main__': sys.exit(main())
