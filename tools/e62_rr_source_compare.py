#!/usr/bin/env python3
"""Compare finalized RR source events, separately from host polling and P1."""
import argparse
import hashlib
import json
from pathlib import Path
import re

EVENT=re.compile(r'E62_P0_EVENT seq=(\d+) vns=(\d+) kind=([A-Z0-9_]+) a=(-?\d+) b=(-?\d+) c=(-?\d+) d=(-?\d+) e=(-?\d+) f=(-?\d+)\b')

def parse(text):
    rows=[]
    for line in text.splitlines():
        if 'E62_P0_EVENT' not in line:continue
        m=EVENT.search(line)
        if not m:raise ValueError('Malformed source event')
        row=(int(m[1]),int(m[2]),m[3],*(int(m[i]) for i in range(4,10)))
        if row[0]!=len(rows)+1 or (rows and row[1]<rows[-1][1]):
            raise ValueError('Missing/reordered source evidence')
        rows.append(row)
    if not rows:raise ValueError('Source evidence unavailable')
    return rows

def compare(record,replay,record_evidence,replay_evidence):
    for name,e in [('record',record_evidence),('replay',replay_evidence)]:
        if e.get('differential_rr_mode')!=name or e.get('qemu_exit_code_after_probe')!=0 or e.get('differential_rr_graceful_shutdown') is not True:
            raise ValueError('Unfinalized or incorrect '+name+' process evidence')
    for field in ('candidate_elf_sha256','native_dshot_scenario','effective_sim_profile'):
        if record_evidence.get(field) is None or record_evidence[field]!=replay_evidence.get(field):
            raise ValueError('Missing/mismatched experiment identity: '+field)
    if record_evidence.get('wiring_failure_reasons'):
        raise ValueError('Record wiring failure: cannot establish complete input')
    expected=record_evidence.get('configured_dshot_frames')
    if not isinstance(expected,int) or expected<=0 or record_evidence.get('passive_source_dshot_completed')!=expected:
        raise ValueError('Record input completion unavailable')
    for name,rows in [('record',record),('replay',replay)]:
        ds=[r[3] for r in rows if r[2]=='DSHOT']
        if ds!=list(range(expected)):raise ValueError('Missing/duplicated '+name+' DShot frame')
    mismatch=next((i for i,(a,b) in enumerate(zip(record,replay)) if a!=b),None)
    exact=mismatch is None and len(record)==len(replay)
    return {'schema':'e62.rr-source-compare.v1','status':'PASS_EXACT_SOURCE_RR_REPLAY' if exact else 'FAIL_SOURCE_RR_MISMATCH',
        'record_events':len(record),'replay_events':len(replay),'dshot_frames':expected,
        'first_mismatch_index':mismatch if mismatch is not None else (min(len(record),len(replay)) if not exact else None),
        'absolute_vns_preserved':True,'host_record_status':record_evidence.get('status'),
        'host_replay_status':replay_evidence.get('status'),'host_replay_exception':replay_evidence.get('exception'),
        'host_missing_observations_reconstructed':False,'p1_qualified':False,'hardware_qualified':False,
        'scope':'ONE_FINALIZED_RECORDING_NOT_INDEPENDENT_A_A_DETERMINISM_OR_MOTOR_QUALIFICATION'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('record','replay','record-evidence','replay-evidence','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args()
    result=compare(parse(a.record.read_text()),parse(a.replay.read_text()),json.loads(a.record_evidence.read_text()),json.loads(a.replay_evidence.read_text()))
    result['input_sha256']={n:hashlib.sha256(getattr(a,n).read_bytes()).hexdigest() for n in ('record','replay','record_evidence','replay_evidence')}
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(result['status'])
    return 0 if result['status'].startswith('PASS') else 1

if __name__=='__main__':raise SystemExit(main())
