#!/usr/bin/env python3
"""Read-only timing decomposition. Original100ns gate stays unchanged."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
RX=re.compile(r'E62_DSHOT_DIAG frame=(\d+) valid=(\d+) deadline=(-?\d+) snapshot=(-?\d+) callback=(-?\d+) wave=(-?\d+) event=(-?\d+) epoch=(-?\d+)')
WIRE=re.compile(r'E62_WIRE_DIAG frame=(\d+) valid=(\d+) deadline=(-?\d+) snapshot=(-?\d+) callback=(-?\d+)')
EVENT=re.compile(r'E62_P0_EVENT seq=\d+ vns=(\d+) kind=DSHOT a=(\d+)\b')

def classify(r):
    if r['deadline']!=r['epoch']+r['frame']*1_000_000:return 'DEADLINE_PROGRAMMING_MISMATCH'
    if r['event']-r['deadline']<=100:return 'WITHIN_EXISTING_BUDGET'
    if r['snapshot']-r['deadline']>100:return 'DISPATCH_SNAPSHOT_LATE'
    if r['callback']-r['deadline']>100:return 'CLOCK_ADVANCED_BETWEEN_DISPATCH_SNAPSHOT_AND_CALLBACK'
    if r['wave']-r['deadline']>100:return 'CLOCK_ADVANCED_INSIDE_CALLBACK_BEFORE_WAVE'
    return 'EVENT_OBSERVATION_AFTER_WAVE_SCHEDULING'

def audit(lines):
    ds={};wire={};source={}
    for line in lines:
        m=RX.search(line)
        if m:
            d=dict(zip(('frame','valid','deadline','snapshot','callback','wave','event','epoch'),map(int,m.groups())))
            if not d['valid'] or d['frame'] in ds:raise ValueError('Missing/duplicate dispatch context')
            ds[d['frame']]=d
        m=WIRE.search(line)
        if m:
            d=dict(zip(('frame','valid','deadline','snapshot','callback'),map(int,m.groups())))
            if not d['valid'] or d['frame'] in wire:raise ValueError('Missing/duplicate wire context')
            wire[d['frame']]=d
        m=EVENT.search(line)
        if m:
            ns,frame=map(int,m.groups())
            if frame in source:raise ValueError('Duplicate DShot source frame')
            source[frame]=ns
    if not ds or sorted(ds)!=list(range(len(ds))) or set(source)!=set(ds) or set(wire)!=set(ds):raise ValueError('Incomplete source/dispatch/first-edge evidence')
    counts=Counter();late=[];maxima=Counter();negative=[]
    for frame,r in ds.items():
        if r['event']!=source[frame]:raise ValueError('Source timestamp differs from saved observation')
        w=wire[frame]
        if w['deadline']!=r['wave']+10000:raise ValueError('First physical edge scheduling mismatch')
        row={**r,'classification':classify(r),'dispatch_snapshot_lateness_ns':r['snapshot']-r['deadline'],'callback_after_snapshot_ns':r['callback']-r['snapshot'],'wave_after_callback_ns':r['wave']-r['callback'],'event_after_wave_ns':r['event']-r['wave'],'event_lateness_ns':r['event']-r['deadline'],'first_wire_callback':w,'wire_lateness_ns':w['callback']-w['deadline']}
        if frame:
            counts[row['classification']]+=1
            for key in ('dispatch_snapshot_lateness_ns','callback_after_snapshot_ns','wave_after_callback_ns','event_after_wave_ns','event_lateness_ns','wire_lateness_ns'):maxima[key]=max(maxima[key],row[key])
            if row['event_lateness_ns']>100:late.append(row)
            if any(row[k]<0 for k in ('callback_after_snapshot_ns','wave_after_callback_ns','event_after_wave_ns')):negative.append(row)
    return {'schema':'e62.dshot-dispatch-audit.v1','status':'SOURCE_DEADLINE_FAILURE_REPRODUCED' if late else 'NO_DEADLINE_FAILURE_REPRODUCED','source_frames':len(ds),'first_frame':ds[0],'epoch_ns':ds[0]['epoch'],'budget_ns':100,'counts':dict(counts),'maxima':dict(maxima),'late_records':late,'negative_clock_deltas':negative,'original_p1_qualified':False,'hardware_qualified':False,'causal_limit':'Observed clock decomposition; host scheduling cause not inferred'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--log',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r=audit(a.log.open());a.output.write_text(json.dumps(r,indent=2)+'\n');print(r['status'])
if __name__=='__main__':main()
