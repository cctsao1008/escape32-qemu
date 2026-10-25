"""Fail-closed T02 acceptance on original unaltered Rel17.3 Guest."""
import json
import sys

def validate(record):
    errors=[]
    stages=record.get('stages',[])
    checks=record.get('autonomous',{}).get('stage_physical_checkpoints',[])
    if record.get('status')!='PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL':
        errors.append('aggregate_not_pass')
    if record.get('issues'):
        errors.append('unresolved_oracle_issues')
    if record.get('dshot_frames_sent')!=110000:
        errors.append('expected_110000_frames')
    if record.get('last_guest_virtual_elapsed_ns',0)<110_000_000_000:
        errors.append('insufficient_guest_virtual_time')
    if len(stages)!=11 or len(checks)!=11:
        errors.append('requires_11_completed_stages')
    for idx in range(11):
        if idx>=len(stages) or idx>=len(checks): break
        cp=checks[idx]; s=stages[idx]
        if not cp.get('valid') or not cp.get('complete'):
            errors.append(f'stage_{idx}_checkpoint_incomplete')
        if cp.get('end_sent_cumulative')!=(idx+1)*10000:
            errors.append(f'stage_{idx}_sent_count_wrong')
        if s.get('sampled_stage_gate',{}).get('status') != 'PASS_SAMPLED_STAGE_DIAGNOSTIC':
            errors.append(f'stage_{idx}_sampled_gate_not_pass')
    if not record.get('autonomous',{}).get('neutral_teardown',{}).get('qualified'):
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
