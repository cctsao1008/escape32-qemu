"""Read-only native pending-TIMG12 fault proof; never a rotor or continuous-pad oracle."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from tools.e62_issue5_cap1_timer_audit import parse

def audit(events,evidence,start_ns=None,expect_pending=True):
    result=dict(schema='e62.pending-timer-fault.v1',status='INCOMPLETE',scope='SIM_ONLY_PENDING_TIMER_OR_TIMING_NEGATIVE_CONTROL',continuous_pad_safety_proven=False,rotor_qualified=False,hardware_qualified=False,failures=[])
    if not events or events[0]['seq']!=1 or any(b['seq']!=a['seq']+1 or b['vns']<a['vns'] for a,b in zip(events,events[1:])):
        result['failures']=['SOURCE_SEQUENCE_OR_TIME_INCOMPLETE'];return result
    anchor=next((e for e in events if e['kind']=='DSHOT' and e['c']>0 and
                 (start_ns is None or e['vns']==start_ns)),None)
    if anchor is None:result['failures']=['SOURCE_DEMAND_ANCHOR_MISSING'];return result
    start_ns=anchor['vns'];result['source_demand']=anchor
    relevant=[e for e in events if e['vns']>=start_ns]
    fault=next((r for r in evidence.get('reference_observer',{}).get('entries',[]) if r['event']==5),None)
    if fault is None:result['failures']=['NO_RETAINED_FIRMWARE_INVALIDITY_OBSERVATION'];return result
    caps=[e for e in relevant if e['kind']=='CAP1'];starts=[e for e in relevant if e['kind']=='T12_START']
    chain=None
    for cap in caps:
        ack=next((e for e in relevant if e['kind']=='CAP1_ACK' and e['vns']>=cap['vns'] and e['c']==cap['a']),None)
        read=next((e for e in relevant if e['kind']=='ECAP1_CAP1_READ' and e['vns']>=cap['vns'] and e['a']==cap['a']),None)
        nxt=next((e for e in starts if ack and read and e['vns']>=max(ack['vns'],read['vns'])),None)
        if nxt is None:continue
        load=next((e for e in reversed(relevant) if e['kind']=='T12_LOAD' and cap['vns']<=e['vns']<=nxt['vns']),None)
        if not load or load['b']<=0:continue
        # CAP1 is a real200MHz ECAP stamp. Do not map a stopped post-fault
        # journal, infer absolute MCU boot time, or fill missing captures.
        delta=((fault['ecap_counter']-cap['a']+2**31)%2**32)-2**31
        mapped=cap['vns']+delta*5
        if mapped<nxt['vns']:continue
        chain=(cap,ack,read,nxt,load,mapped);break
    if chain is None:result['failures']=['ACCEPTED_CAPTURE_TIMER_CHAIN_INCOMPLETE'];return result
    cap,ack,read,timer,load,observed=chain
    # Verify local native counter scale with actual source CAP/VBUS_ZERO
    # anchors rather than assuming every MCU clock is a QEMU timestamp.
    zeros=[e for e in events if e['kind']=='ECAP1_CAP1_READ' and cap['vns']<=e['vns']<=observed+10000]
    if not zeros:result['failures']=['ECAP_COUNTER_ANCHOR_INCOMPLETE'];return result
    scale_errors=[e['vns']-(cap['vns']+(((e['b']-cap['a']+2**31)%2**32)-2**31)*5) for e in zeros]
    if any(abs(x)>5 for x in scale_errors):result['failures']=['ECAP_LOCAL_CLOCK_MAPPING_NOT_VERIFIED'];return result
    period=(load['a']+1)*1_000_000_000/load['b'];deadline=timer['vns']+period
    stop=next((e for e in relevant if e['kind']=='T12_STOP' and e['vns']>=observed-5),None)
    off=next((e for e in relevant if e['kind']=='SWITCH_FOCUS' and e['vns']>=observed-5 and e['a']==0 and e['b']==0),None)
    result.update(source_capture=cap,source_ack=ack,source_read=read,source_timer_start=timer,source_load=load,deadline_virtual_ns=deadline,firmware_invalidity_record=fault,invalidity_observation_vns_interval=[observed-5,observed+5],ecap_anchor_errors_ns=scale_errors,source_stop=stop,source_first_sampled_all_off=off)
    replaced=any(e['kind']=='T12_START' and timer['vns']<e['vns']<=observed+5 for e in relevant)
    counter_error=(deadline-stop['vns']-stop['a']*1_000_000_000/load['b']) if stop else None
    pending=bool(stop and not replaced and stop['c']==1 and stop['b']==load['a'] and stop['a']>0 and
                 timer['vns']<observed-5 and observed+5<stop['vns']<deadline and
                 abs(counter_error)<=1_000_000_000/load['b'])
    result.update(timer_replaced_before_fault=replaced,remaining_counter_consistency_error_ns=counter_error)
    irqs=[e for e in relevant if e['kind']=='TIMG12' and timer['vns']<=e['vns']<=observed+5]
    result['pending_cancellation_proven']=pending
    if not off or (expect_pending and not stop):result['failures'].append('SHUTDOWN_OBSERVATIONS_INCOMPLETE');return result
    bad=[e for e in relevant if e['vns']>observed+5 and (e['kind'] in ('PWM_PAIR','T12_START','TIMG12','CAP1_ACK') or (e['kind']=='SWITCH_FOCUS' and e['vns']>off['vns'] and (e['a'] or e['b'])))]
    result.update(post_invalidity_unintended_events=bad,observed_invalidity_to_all_off_ns_interval=[off['vns']-observed-5,off['vns']-observed+5],final_clocked_evaluator=evidence.get('pwm_source_after'),source_horizon_ns=events[-1]['vns'],timer_irqs_before_invalidity=irqs)
    if bad:result['failures'].append('POWER_OR_TIMER_AFTER_KNOWN_INVALIDITY')
    if expect_pending and not pending:result['failures'].append('REQUESTED_PENDING_CONDITION_NOT_EXERCISED')
    if not expect_pending and not irqs:result['failures'].append('POST_DEADLINE_CONTROL_NOT_EXERCISED')
    if fault.get('latest_valid')!=0 or not fault.get('fresh'):result['failures'].append('INVALID_ONLY_WHILE_OLD_ASSOCIATION_FRESH_NOT_PROVEN')
    final=evidence.get('pwm_source_after',{})
    if final.get('instantaneous_six_pad_mask')!=0 or final.get('running') is not False:result['failures'].append('FINAL_CLOCKED_OFF_NOT_PROVEN')
    result['status']='FAIL' if result['failures'] else 'PASS_NEW'
    result['qualification_limit']='Bounded source SWITCH_FOCUS plus final evaluator, not continuous pad measurement or a general shutdown-latency limit. Manual UNIT IRQ interleavings are separate.'
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('events','evidence','output'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--post-deadline-control',action='store_true');a=p.parse_args();r=audit(parse(a.events.read_text()),json.loads(a.evidence.read_text()),expect_pending=not a.post_deadline_control);a.output.write_text(json.dumps(r,indent=2)+'\n');print(r['status']);return r['status']!='PASS_NEW'
if __name__=='__main__':raise SystemExit(main())
