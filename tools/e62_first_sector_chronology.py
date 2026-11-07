"""Source-owned sampled torque partition. No inferred captures, interpolated rotor or P1 waiver."""
import argparse,json,math
from pathlib import Path
from tools.e62_issue5_cap1_timer_audit import parse,classify

PHASES=('A','B','C')
def rotor(e,at=None):
    if e is None:return None
    return dict(vns=e['vns'],sample_age_ns=None if at is None else at-e['vns'],rpm=e['a']/1000,electrical_angle_rad=e['b']/1000,electrical_angle_deg=e['b']/1000*180/math.pi,current_a=[e[k]/1000 for k in ('c','d','e')],torque_nm=e['f']/1e6)
def pair(e):
    if e is None:return None
    hi=(e['a']-1)//3;lo=(e['a']-1)%3
    if not(0<=hi<3 and 0<=lo<3 and hi!=lo and e['b']==(1<<(2*hi))+(1<<(2*lo+1))):raise ValueError('Inconsistent physical PWM pair')
    return dict(source=e,high=PHASES[hi],low=PHASES[lo],floating=next(p for i,p in enumerate(PHASES) if i not in (hi,lo)))
def state(events,when,focus):
    before=next((e for e in reversed(events) if e['kind']=='ROTOR' and e['vns']<=when),None)
    after=next((e for e in events if e['kind']=='ROTOR' and e['vns']>when),None)
    switch=next((e for e in reversed(events) if e['kind']=='SWITCH_FOCUS' and e['vns']<=when),None)
    limited=any(e['kind']=='SWITCH_FOCUS_LIMIT' and e['vns']<=when for e in events)
    valid=bool(focus and focus[0]<=when<=focus[1] and switch and switch['vns']>=focus[0] and not limited)
    pads=None
    if valid:
        pads=dict(source_vns=switch['vns'],state_age_ns=when-switch['vns'],mask=switch['a'],gate_enabled=bool(switch['b']),gate_word=switch['c'],on_pads=[PHASES[p]+('_H' if not leg else '_L') for p in range(3) for leg in (0,1) if switch['a']&(1<<(2*p+leg))],status='SOURCE_TRANSITION_HELD_WITHIN_BOUNDED_WINDOW')
    return dict(rotor_before=rotor(before,when),rotor_after=rotor(after,when),pads=pads,pad_status='OBSERVED' if valid else 'INCOMPLETE_SOURCE_SWITCH_WINDOW')
def phase_of(t,cap,start,irq,changed):
    if cap is None:return 'NO_OBSERVED_ACCEPTED_CAPTURE'
    if t<cap:return 'BEFORE_ACCEPTED_CAPTURE'
    if start is None or t<start:return 'CAPTURE_TO_SCHEDULE_TRANSITION'
    if irq is None or t<irq:return 'SCHEDULED_WAIT_BEFORE_IRQ'
    if changed is None or t<changed:return 'IRQ_TO_PHYSICAL_PAIR_CHANGE'
    return 'AFTER_FIRST_PHYSICAL_PAIR_CHANGE'
def demand(events,evidence,anchor,end,focus,policy,index):
    t=anchor['vns'];window=min(end,t+50_000_000)
    drive=next((e for e in events if e['kind']=='PWM_PAIR' and t<=e['vns']<window),None)
    irq=next((e for e in events if e['kind']=='TIMG12' and drive and drive['vns']<e['vns']<window),None)
    changed=next((e for e in events if e['kind']=='PWM_PAIR' and drive and drive['vns']<e['vns']<window and e['a']!=drive['a']),None)
    chains=classify(events,t,window)
    accepted=next((c for c in chains if c['classification']=='READ_AND_TIMER_PROGRAMMED'),None)
    cap=accepted['cap1_ns'] if accepted else None;start=accepted['timer_start_ns'] if accepted else None
    samples=[];negative={}
    for e in events:
        if e['kind']!='ROTOR' or not t<=e['vns']<window:continue
        row=rotor(e);row['after_demand_ns']=e['vns']-t;row['feedback_phase']=phase_of(e['vns'],cap,start,irq['vns'] if irq else None,changed['vns'] if changed else None)
        row['physical_first_sector']=bool(drive and drive['vns']<=e['vns'] and (changed is None or e['vns']<changed['vns']))
        if row['torque_nm']<0:negative.setdefault(row['feedback_phase'],[]).append(row['vns'])
        samples.append(row)
    history=evidence.get('issue5_bemf_first_history',{}).get('entries',[]) if index==0 and not any(e['kind']=='CAP1' and e['vns']<t for e in events) else []
    decisions=[]
    for h in history:
        if len(decisions)>=len(chains):break
        if h['decision']=='TIMEOUT':break # Do not invent a CAP1 for a timeout.
        row=dict(h);row['candidate_ignore_before_us']=(h['ival_before']>>2 if policy=='firstedge' and h['sync_before']==0 else h['ival_before']>>1);row['source_capture_order_match']=chains[len(decisions)]['cap1_ns'];decisions.append(row)
    ledger=[]
    relevant={'PWM_PAIR','CAP1','CAP1_ACK','ECAP1_CAP1_READ','T12_LOAD','T12_START','TIMG12','TIMG12_ACK','CMP_FILTER'}
    for e in events:
        if e['kind'] in relevant and t<=e['vns']<window:
            ledger.append(dict(source=e,after_demand_ns=e['vns']-t,**state(events,e['vns'],focus)))
    motion=[]
    offsets=(0,-2*math.pi/3,2*math.pi/3)
    for e in events:
        if e['kind']!='CMP_FILTER' or not t<=e['vns']<window or not 0<=e['a']<3:continue
        around=state(events,e['vns'],focus);a=around['rotor_before'];b=around['rotor_after']
        kind='INCOMPLETE_ROTOR_BRACKET';sa=sb=None
        if a and b:
            sa=math.sin(a['electrical_angle_rad']+offsets[e['a']]);sb=math.sin(b['electrical_angle_rad']+offsets[e['a']])
            if a['rpm']*b['rpm']<0 and sa*sb>0 and min(abs(sa),abs(sb))>.2:kind='RPM_SIGN_CHANGE_WITH_STABLE_PHASE_SINE'
            elif a['rpm']*b['rpm']>0 and sa*sb<0:kind='CONSISTENT_WITH_SPATIAL_SINE_CROSSING'
            else:kind='UNRESOLVED_AT_SAMPLED_RESOLUTION'
        motion.append(dict(source=e,classification=kind,phase_sine_before=sa,phase_sine_after=sb,rotor_before=a,rotor_after=b))
    return dict(comparator_transition_geometry=motion,source_demand=anchor,window_end_ns=window,boundary=state(events,t,focus),first_pair=pair(drive),first_changed_pair=pair(changed),first_commutation_irq=irq,first_accepted_capture_with_timer_chain=accepted,capture_timer_chains=chains,first_guest_decisions_order_correlated=decisions,guest_decision_limit='First-demand ordered correlation only; timeout or capped history not filled. Later demand acceptance is inferred from actual read/ACK and timer programming, not a fabricated Guest decision.',negative_torque_samples_by_feedback_phase={k:dict(count=len(v),sample_vns=v) for k,v in negative.items()},first_sector_negative_samples=sum(s['torque_nm']<0 and s['physical_first_sector'] for s in samples),first_reversed_sample=next((s for s in samples if s['rpm']<=-50),None),samples=samples,source_ledger=ledger)
def analyze(events,evidence,focus=None,policy='baseline'):
    if not events or events[0]['seq']!=1 or any(b['seq']!=a['seq']+1 or b['vns']<a['vns'] for a,b in zip(events,events[1:])):raise ValueError('Source sequence/time gap')
    ds=[e for e in events if e['kind']=='DSHOT'];anchors=[e for i,e in enumerate(ds) if e['c']>0 and (i==0 or ds[i-1]['c']==0)]
    if not anchors:raise ValueError('Missing source positive demand')
    demands=[]
    for index,a in enumerate(anchors):
        end=next((e['vns'] for e in ds if e['vns']>a['vns'] and e['c']==0),events[-1]['vns']+1)
        demands.append(demand(events,evidence,a,end,focus,policy,index))
    return dict(schema='e62.first-sector-source-chronology.v1',policy_identity=policy,demands=demands,scope='SAMPLED_SOURCE_DIAGNOSTIC_NOT_QUALIFICATION',negative_torque_limit='Counts and timestamps of actual 1ms samples, not integrated negative-torque impulse or continuous-duration measurements.',model_uncertainty='Uncalibrated native sinusoidal phase BEMF, terminal-equivalent Kt, inertia, no-load and virtual analog network remain hypotheses for physical behavior.',p1_qualified=False,hardware_qualified=False)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('events','evidence','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--focus-ms');p.add_argument('--policy',choices=('baseline','firstedge','adc2k'),default='baseline');a=p.parse_args();focus=tuple(int(v)*1000000 for v in a.focus_ms.split(':')) if a.focus_ms else None
    r=analyze(parse(a.events.read_text()),json.loads(a.evidence.read_text()),focus,a.policy);a.output.write_text(json.dumps(r,indent=2)+'\n')
if __name__=='__main__':main()
