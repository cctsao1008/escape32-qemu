#!/usr/bin/env python3
"""Source supply -> native acquisition -> calibrated publication, never rotor PASS."""
import argparse,json,re
from pathlib import Path
RX=re.compile(r'(E62_VBUS_SOURCE|E62_VBUS_EOC|E62_VBUS_READ|E62_VBUS_ADC_CLOCK_STOP|E62_DAC_SHADOW|E62_DAC_ACTIVE|E62_VBUS_ZERO) (.*)')
KV=re.compile(r'(\w+)=(-?\d+)')
def rounded(n,d):return (n+d//2)//d

def convert(raw):
    if not 0<raw<4095:return None
    pin=rounded(raw*3300000,4096);bus=rounded(pin*160,11)
    phase=rounded(bus,100)+1410000
    return rounded(phase*4096,3300000)-1

def parse(lines):
    out=[]
    for line in lines:
        m=RX.search(line)
        if m:out.append({'kind':m[1],**{k:int(v) for k,v in KV.findall(m[2])}})
    return out

def audit(events,evidence):
    sources=[r for r in events if r['kind']=='E62_VBUS_SOURCE'];eocs={};reads=[];errors=[]
    if not sources:raise ValueError('Missing source-owned supply events')
    for r in events:
        if r['kind']=='E62_VBUS_EOC':
            source=next((s for s in reversed(sources) if s['vns']<=r['acquisition']),None)
            if source is None:errors.append('ACQUISITION_WITHOUT_INPUT_EPOCH');continue
            expected=0 if source['sensor_mode']==1 else rounded(source['mv']*4096*11,528000)
            if r['code']!=expected or r['acquisition']>r['vns'] or r['channel']!=12 or r['soc']!=1:errors.append('ADC_ACQUISITION_OR_ROUTE_MISMATCH')
            if r['sample'] in eocs:errors.append('DUPLICATE_EOC_SAMPLE')
            eocs[r['sample']]=r
        if r['kind']=='E62_VBUS_READ':
            a=eocs.get(r['sample'])
            if a is None or a['code']!=r['code'] or a['vns']>r['vns']:errors.append('READ_NOT_ASSOCIATED_WITH_COMPLETED_SAMPLE')
            reads.append(r)
    journal=evidence.get('reference_observer',{});rows=journal.get('entries',[]);byseq={r['seq']:r for r in rows};handovers=[]
    for request in [r for r in rows if r['event']==8]:
        key=lambda r:all(r[k]==request[k] for k in ('sample','expected_code','blackout_epoch','selected_code'))
        loaded=next((r for r in rows if r['seq']>request['seq'] and r['event']==9 and key(r)),None)
        pub=next((r for r in rows if loaded and r['seq']>loaded['seq'] and r['event']==6 and key(r)),None)
        h={'request':request,'loaded':loaded,'published':pub,'complete':False}
        if loaded and pub:
            complete=all(i in byseq for i in range(request['seq'],pub['seq']+1))
            sample=eocs.get(request['sample']);target=convert(sample['code']) if sample else None
            shadow=next((r for r in events if r['kind']=='E62_DAC_SHADOW' and r['sample']==request['sample'] and r['code']==request['expected_code']),None)
            active=next((r for r in events if shadow and r['kind']=='E62_DAC_ACTIVE' and r['vns']>=shadow['vns'] and r['code']==request['expected_code']),None)
            zero_count=None;pub_ns=None
            if active:
                pub_ns=active['vns']+((pub['ecap_counter']-active['counter'])&0xffffffff)*20
                zero_count=sum(r['kind']=='E62_VBUS_ZERO' and active['vns']<r['vns']<=pub_ns for r in events)
            h.update(sample=sample,independent_calculated_code=target,shadow=shadow,active=active,estimated_publication_vns_from_native_counter=pub_ns,zero_events_after_load=zero_count)
            h['complete']=bool(complete and sample and target==request['expected_code'] and shadow and active and
                shadow['cap_enabled']==0 and active['cap_enabled']==0 and
                active['mux']==(request['selected_code']&3)-1 and
                active['edge']==(0 if request['selected_code']&4 else 1) and
                not request['published'] and not loaded['published'] and not loaded['armed'] and
                pub['published'] and pub['ready'] and pub['fresh'] and pub['latest_valid'] and
                pub['age_ticks']<=pub['max_age_ticks'] and zero_count is not None and zero_count>=2)
        handovers.append(h)
    fault=next((r for r in rows if r['event']==5),None);shutdown=next((r for r in rows if r['event']==11),None)
    invalid=any(s['sensor_mode']==1 for s in sources);stale=any(s['sensor_mode']==2 for s in sources)
    failure_closed=bool(fault and shutdown and not shutdown['armed'] and not shutdown['published'] and not shutdown['ready'] and evidence.get('native_motor',{}).get('actual_pwm_six_bit_mask')==0)
    if stale:failure_closed=failure_closed and bool(any(r['kind']=='E62_VBUS_ADC_CLOCK_STOP' for r in events)) and fault['age_ticks']>fault['max_age_ticks']
    if invalid:failure_closed=failure_closed and bool(any(r['code']==0 for r in eocs.values())) and not fault['latest_valid']
    positive=bool(len(handovers)>=2 and all(h['complete'] for h in handovers) and not errors)
    return {'schema':'e62.source-vbus-handover.v1','status':('FAIL_CLOSED_OBSERVED' if failure_closed and not errors else 'INCOMPLETE_FAIL_CLOSED') if invalid or stale else ('SPECIFIC_SOURCE_HANDOVERS_VERIFIED' if positive else 'INCOMPLETE_HANDOVER_EVIDENCE'),'sources':sources,'adc_eoc_samples':len(eocs),'adc_reads':len(reads),'source_errors':errors,'handovers':handovers,'fault_entry':fault,'post_shutdown':shutdown,'bounded_journal_missing_ranges':journal.get('missing_sequence_ranges'),'reference_network':'SIM_ONLY1.41V+.02*(VBUS/2+BEMF); VBUS11/160; ADC/DAC3.3V','counter_mapping':'Native ECAP20ns/count, checked locally against source timestamps; not host clock','p1_qualified':False,'rotor_synchronized':False,'hardware_qualified':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--log',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=audit(parse(a.log.open()),json.loads(a.evidence.read_text()));a.output.write_text(json.dumps(r,indent=2)+'\n');print(r['status'])
if __name__=='__main__':main()
