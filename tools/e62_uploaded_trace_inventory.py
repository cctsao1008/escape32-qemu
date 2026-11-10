#!/usr/bin/env python3
"""Read-only partial-provenance archive replay; never grants qualification.

The strict manifest/P1 readers and their budgets remain unchanged. This
streaming archive reader validates the complete supplied record independently;
missing scenario/CFG/build bytes remain missing, never synthesized.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.e62_acquisition_timeline import ORIGINAL,PRODUCTION,rotor
from tools.e62_lifecycle_alignment import align
from tools.native_p0_strict import EVENT,KINDS
from tools.native_p1_qualification import dshot_value
from tools.e62_issue5_cap1_timer_audit import classify
from tools.e62_acquisition_timeline import OBSERVER_KINDS

MAX_BYTES=64*1024*1024  # archive resource bound, never a P1 gate change

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def records(path):
    if path.stat().st_size>MAX_BYTES:raise ValueError('Archive file resource bound exceeded')
    previous_ns=-1;seq=0
    with path.open() as stream:
        for line in stream:
            if 'E62_P0_EVENT ' not in line:continue
            m=EVENT.search(line)
            if not m:raise ValueError('Malformed source event')
            n,ns,kind=int(m[1]),int(m[2]),m[3]
            if n!=seq+1 or ns<previous_ns or ns<0:raise ValueError('Missing/reordered source event')
            if kind not in KINDS|OBSERVER_KINDS:raise ValueError('Unknown source event: '+kind)
            seq=n;previous_ns=ns
            yield dict(seq=n,vns=ns,kind=kind,data=[int(m[i]) for i in range(4,10)])
    if not seq:raise ValueError('No source evidence')

def family(e):
    a=e.get('candidate_elf_sha256');b=e.get('original_elf_sha256')
    if not isinstance(a,str) or len(a)!=64 or any(c not in '0123456789abcdef' for c in a):raise ValueError('Invalid declared ELF SHA256')
    if not a or a!=b:raise ValueError('Conflicting/missing declared ELF identity')
    return {ORIGINAL:'original_rel17_3',PRODUCTION:'production_root_fixes'}.get(a,'experimental_candidate')

def anchors(rows,e):
    """Validate embedded stage declarations against every actual DShot event."""
    meta=e['native_dshot_scenario'];stages=meta['stages'];ds=[r for r in rows if r['kind']=='DSHOT']
    if meta['frame_period_ns']!=1_000_000 or meta['guest_ready_gating'] is not False:raise ValueError('Unsupported DShot declaration')
    if not stages or any(len(s)!=4 or any(type(x)is not int for x in s) or s[0]<=0 or s[1]!=s[2] or s[3]!=1 or not 0<=s[1]<=1000 for s in stages):raise ValueError('Only declared hold stages supported')
    total=sum(s[0] for s in stages)
    if len(ds)!=total or e.get('p0_source_event_count')!=len(rows) or e.get('configured_dshot_frames')!=total or e.get('autonomous_dshot',{}).get('sent')!=total:raise ValueError('Source/evidence count mismatch')
    epoch=ds[1]['vns']-1_000_000 if len(ds)>1 else ds[0]['vns'];at=0;result=[]
    for stage,(duration,permille,_,_) in enumerate(stages):
        result.append((stage,permille,ds[at]))
        command=dshot_value(permille)
        for n in range(at,at+duration):
            ev=ds[n];late=ev['vns']-(epoch+n*1_000_000)
            if ev['data'][:3]!=[n,stage,command] or not 0<=late<=(970000 if n==0 else 100):raise ValueError('DShot declaration/source mismatch')
        at+=duration
    return result

def boundary(rows,stage,command,anchor):
    prior=[r for r in rows if r['seq']<anchor['seq']]
    following=next((r for r in rows if r['seq']>=anchor['seq'] and r['kind']=='ROTOR'),None)
    before=next((r for r in reversed(prior) if r['kind']=='ROTOR'),None)
    switch=next((r for r in reversed(prior) if r['kind'] in ('SWITCH','SWITCH_FOCUS')),None)
    clock=next((r for r in reversed(prior) if r['kind']=='PWM_TBCTL'),None)
    age=None if before is None else anchor['vns']-before['vns'];s_age=None if switch is None else anchor['vns']-switch['vns']
    fresh=age is not None and age<=1_000_000;sfresh=s_age is not None and s_age<=2_000_000
    return dict(stage=stage,command_permille=command,seq=anchor['seq'],vns=anchor['vns'],rotor_before=rotor(before,anchor['vns']),rotor_after=rotor(following,anchor['vns']),rotor_age_ns=age,rotor_status='OBSERVED' if fresh else 'INCOMPLETE',switch_before=switch,switch_age_ns=s_age,switch_status='OBSERVED' if sfresh else 'INCOMPLETE',gate_active=bool(switch['data'][1]) if sfresh else None,pwm_pad_mask=switch['data'][0]&63 if sfresh else None,clock_before=clock)

def observe(rows,e):
    f=family(e)
    if any(e.get(k) is not False for k in ('host_guest_register_writes','synthetic_timed_bemf_enabled','used_guest_wfi_or_gdb')):raise ValueError('No-injection provenance absent or violated')
    bounds=[boundary(rows,*a) for a in anchors(rows,e)]
    stages=[]
    for i,b in enumerate(bounds):
        end=bounds[i+1]['seq'] if i+1<len(bounds) else len(rows)+1
        window=[r for r in rows if b['seq']<=r['seq']<end]
        kinds=('PWM_PAIR','CMP_FILTER','CAP1','CAP1_ACK','ECAP1_CAP1_READ','T12_LOAD','T12_START','TIMG12','TIMG12_ACK')
        flat=[dict(seq=r['seq'],vns=r['vns'],kind=r['kind'],**dict(zip('abcdef',r['data']))) for r in window if r['vns']<=b['vns']+25_000_000]
        chain=classify(flat,b['vns'],b['vns']+25_000_000) if flat else []
        if chain:chain[-1]['classification']='INCOMPLETE_RIGHT_CENSORED'
        stages.append({'stage':i,'cap1_windows_first_25ms':chain,'first_events':{k:next((r for r in window if r['kind']==k),None) for k in kinds},'first_negative_50rpm_sample':next((rotor(r,b['vns']) for r in window if r['kind']=='ROTOR' and r['data'][0]<=-50000),None)})
    source={'boundaries':bounds,'provenance':{'firmware_class':f,'declared_elf_sha256':e['candidate_elf_sha256'],'binary_independently_verified':False,'status':'INCOMPLETE_PROVENANCE'},'reference_acquisition_status':'INCOMPLETE_NO_SAMPLE_EPOCH_OR_PUBLICATION_IDENTITY'}
    life=align(rows,source);overlay=life.pop('overlay');life['overlay_record_count']=len(overlay);life['overlay_storage']='Original raw source log; no event copied or synthesized'
    return dict(status='OBSERVED_SOURCE_WITH_INCOMPLETE_PROVENANCE',source_events=len(rows),kind_counts=dict(Counter(r['kind'] for r in rows)),declared_firmware_class=f,declared_elf_sha256=e['candidate_elf_sha256'],declared_scenario_sha256=e['native_dshot_scenario']['sha256'],scenario_bytes_verified=False,cfg_available=False,qemu_build_identity_verified=False,elf_bytes_verified=False,reported_effective_profile=e.get('effective_sim_profile'),boundaries=bounds,stage_first_events=stages,lifecycle=life,diagnostic_sample_age_budgets_ns={'rotor':1_000_000,'switch':2_000_000},p1_criteria_changed=False,p1_qualified=False,hardware_qualified=False)

def pair(a,b,ea,eb):
    fields=('candidate_elf_sha256','native_dshot_scenario','effective_sim_profile','requested_mcpwm_root_clock_hz','requested_sim_bemf_waveform','source_focus_window_ms','differential_sync_start','experimental_bemf_robustness')
    same=all(ea.get(k)==eb.get(k) for k in fields)
    index=next((i for i,(x,y) in enumerate(zip(a,b)) if x!=y),min(len(a),len(b)) if len(a)!=len(b) else None)
    return dict(status='RAW_SOURCE_DIVERGENCE' if index is not None else 'IDENTICAL_RAW_EVENTS',same_reported_settings=same,matched_provenance_verified=False,first_mismatch_index=index,a=a[index] if index is not None and index<len(a) else None,b=b[index] if index is not None and index<len(b) else None,causal_attribution='NOT_ESTABLISHED_MISSING_CFG_AND_BUILD_IDENTITY')

def audit(directory,output):
    output.mkdir(parents=True,exist_ok=True);cases=[];pairs=[];errors=[]
    for p in sorted(directory.glob('*.json')):
        name=p.stem;raw=p.with_suffix('.p0.events.log');qemu=p.with_suffix('.qemu.log');stdout=p.with_suffix('.stdout.log')
        try:
            e=json.loads(p.read_text());rows=list(records(raw));observed=observe(rows,e)
            if list(records(qemu))!=rows or qemu.stat().st_size!=e['qemu_log_bytes']:raise ValueError('Full QEMU log/raw event copy mismatch')
            final=[json.loads(line.split(' ',1)[1]) for line in stdout.read_text().splitlines() if line.startswith('E62_NATIVE_AUTONOMOUS_NO_WFI_PROBE ')]
            if len(final)!=1 or final[0]!=e:raise ValueError('stdout/JSON summary mismatch')
            observed.update(dataset=name,files={str(f.name):{'sha256':sha(f),'bytes':f.stat().st_size} for f in (p,raw,qemu,stdout)},raw_and_qemu_events_match=True,stdout_and_json_match=True)
            (output/(name+'.observations.json')).write_text(json.dumps(observed,indent=2)+'\n');cases.append(observed)
            if name.endswith('repeat01'):
                peer=p.with_name(name[:-2]+'02.json')
                if peer.exists():pairs.append(dict(dataset_a=name,dataset_b=peer.stem,**pair(rows,list(records(peer.with_suffix('.p0.events.log'))),e,json.loads(peer.read_text()))))
        except (OSError,ValueError,TypeError,KeyError) as exc:errors.append(dict(dataset=name,error=str(exc),status='INCOMPLETE'))
    report={'schema':'e62.uploaded-trace-inventory.v1','status':'INCOMPLETE_PROVENANCE' if cases and not errors else 'INCOMPLETE_SOURCE_OR_PROVENANCE','cases':cases,'comparisons':pairs,'errors':errors,'missing':['standalone scenario JSON bytes','CFG flash image and hash','guest ELF bytes/source build manifest','QEMU executable hash/source/build manifest','exact launch command/configuration manifest'],'p1_qualified':False,'hardware_qualified':False}
    (output/'inventory.json').write_text(json.dumps(report,indent=2)+'\n');return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=audit(a.directory,a.output);print(json.dumps({'status':r['status'],'cases':len(r['cases']),'errors':r['errors']}));return 1 if r['errors'] or not r['cases'] else 0
if __name__=='__main__':raise SystemExit(main())
