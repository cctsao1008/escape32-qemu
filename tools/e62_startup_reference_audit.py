"""Narrow source replay: keep physical captures, firmware decisions and rotor samples distinct."""
import argparse,json
from pathlib import Path
from tools.e62_issue5_cap1_timer_audit import parse,classify
from tools.e62_vbus_handover_audit import parse as analog_parse,rounded

def analyze(events,analog,evidence,frame):
    anchor=next(e for e in events if e['kind']=='DSHOT' and e['a']==frame)
    t=anchor['vns'];prior=next((e for e in reversed(events) if e['kind']=='ROTOR' and e['vns']<=t),None)
    drive=next((e for e in events if e['kind']=='PWM_PAIR' and e['vns']>=t),None)
    reverse=next((e for e in events if e['kind']=='ROTOR' and e['vns']>=t and e['a']<=-50000),None)
    captures=[e for e in events if e['kind']=='CAP1' and e['vns']>=t]
    timers=[e for e in events if e['kind']=='TIMG12' and e['vns']>=t]
    decisions=evidence.get('issue5_bemf_first_history',{}).get('entries',[])
    zeros=[e for e in analog if e['kind']=='E62_VBUS_ZERO'];tick_ns=None
    if len(zeros)>=2:
        dn=zeros[1]['vns']-zeros[0]['vns'];dc=(zeros[1]['counter']-zeros[0]['counter'])&0xffffffff
        if dc and abs(dn-dc*rounded(dn,dc))<=rounded(dn,dc):tick_ns=rounded(dn,dc)
    # First two same-phase CAP1 loads precede the first commutation; the
    # pinned backend keeps the native counter continuous across rejection.
    if tick_ns is None and len(captures)>=2 and captures[0]['b']==captures[1]['b'] and (not timers or captures[1]['vns']<timers[0]['vns']):
        dn=captures[1]['vns']-captures[0]['vns'];dc=(captures[1]['a']-captures[0]['a'])&0xffffffff
        if dc and dn%dc==0:tick_ns=dn//dc
    bracket={}
    if reverse and captures and tick_ns:
        rows=evidence.get('reference_observer',{}).get('entries',[])
        mapped=[dict(r,source_counter_mapped_observation_vns=captures[0]['vns']+(((r['ecap_counter']-captures[0]['a']+2**31)%2**32)-2**31)*tick_ns) for r in rows]
        before=[r for r in mapped if r['source_counter_mapped_observation_vns']<=reverse['vns']]
        after=[r for r in mapped if r['source_counter_mapped_observation_vns']>=reverse['vns']]
        bracket=dict(before=max(before,key=lambda r:r['source_counter_mapped_observation_vns']) if before else None,after=min(after,key=lambda r:r['source_counter_mapped_observation_vns']) if after else None)
    return dict(schema='e62.startup-reference-replay.v1',dshot_source_anchor=anchor,
        preceding_sample=prior,preceding_sample_age_ns=t-prior['vns'] if prior else None,
        boundary_instantaneous_gate_state='INCOMPLETE_BOUNDED_SWITCH_LOG',
        first_drive_pair=drive,first_significant_reverse_sample=reverse,
        reversal_after_demand_ns=reverse['vns']-t if reverse else None,
        first_two_captures=captures[:2],first_commutation_irq=timers[0] if timers else None,
        first_two_firmware_decisions=decisions[:2],
        capture_and_first_history_counts=dict(source_captures=len(captures),retained_decisions=len(decisions)),
        first_capture_timer_chains=classify(events,t,captures[2]['vns'] if len(captures)>2 else events[-1]['vns'])[:2],
        reference_observations_bracketing_reversal=bracket,observed_ecap_tick_ns=tick_ns,
        evidence_limit='Journal observations bracket the sampled reversal; they do not prove continuous state between observations. CAP1 is not acceptance; six-step count is not rotor synchronization.',
        startup_verdict='FAILED_SIGNIFICANT_REVERSAL' if reverse else 'INCOMPLETE_NOT_QUALIFIED',
        flying_restart_verdict='NOT_EXERCISED_BY_THIS_SCENARIO',p1_qualified=False,hardware_qualified=False)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('log','evidence','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--frame',type=int,required=True);a=p.parse_args();text=a.log.read_text();r=analyze(parse(text),analog_parse(text.splitlines()),json.loads(a.evidence.read_text()),a.frame);a.output.write_text(json.dumps(r,indent=2)+'\n');print(r['startup_verdict'])
if __name__=='__main__':main()
