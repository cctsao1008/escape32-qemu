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
        if line.startswith('[R '):
            q=re.search(r' (read[bwlq]?|write[bwlq]?|b64read) (0x[0-9a-fA-F]+)(?: (0x[0-9a-fA-F]+))?',line)
            if q:
                addr=int(q[2],16);size={'readb':1,'readw':2,'readl':4,'readq':8}.get(q[1],int(q[3],16) if q[3] else 4)
                if addr<0x4000b020 and addr+size>0x4000b000:out.append({'kind':'HOST_ADC_RESULT_ACCESS','address':addr})
        m=RX.search(line)
        if m:out.append({'kind':m[1],**{k:int(v) for k,v in KV.findall(m[2])}})
    return out

def audit(events,evidence):
    sources=[r for r in events if r['kind']=='E62_VBUS_SOURCE'];eocs={};reads=[];errors=[]
    if not sources:raise ValueError('Missing source-owned supply events')
    if any(r['kind']=='HOST_ADC_RESULT_ACCESS' for r in events):errors.append('HOST_ADC_RESULT_ACCESS_CONFOUND')
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
            zero_count=None;pub_ns=None;mapping_errors=[];tick_ns=None
            if active:
                basis=[r for r in events if r['kind']=='E62_VBUS_ZERO' and r['vns']>=active['vns']][:2]
                if len(basis)==2:
                    dn=basis[1]['vns']-basis[0]['vns'];dc=(basis[1]['counter']-basis[0]['counter'])&0xffffffff
                    if dc:tick_ns=rounded(dn,dc)
                    if not tick_ns or abs(dn-dc*tick_ns)>tick_ns:tick_ns=None
                if tick_ns:
                    pub_ns=active['vns']+((pub['ecap_counter']-active['counter'])&0xffffffff)*tick_ns
                    zeros=[r for r in events if r['kind']=='E62_VBUS_ZERO' and active['vns']<r['vns']<=pub_ns]
                    zero_count=len(zeros)
                    mapping_errors=[r for r in zeros if abs((r['vns']-active['vns'])-((r['counter']-active['counter'])&0xffffffff)*tick_ns)>tick_ns]
                    if not 0<=pub_ns-active['vns']<=request['max_age_ticks']*62500:mapping_errors.append({'error':'COUNTER_EPOCH_OR_DEADLINE_MISMATCH'})
            matched_read=next((r for r in reads if sample and shadow and r['sample']==request['sample'] and r['code']==sample['code'] and sample['vns']<=r['vns']<=shadow['vns']),None)
            h.update(sample=sample,guest_adc_read=matched_read,independent_calculated_code=target,shadow=shadow,active=active,software_ready_observation_vns_from_native_counter=pub_ns,zero_events_after_load=zero_count,counter_mapping_errors=mapping_errors,observed_ecap_tick_ns=tick_ns)
            h['complete']=bool(complete and sample and matched_read and target==request['expected_code'] and shadow and active and
                shadow['cap_enabled']==0 and active['cap_enabled']==0 and
                active['mux']==(request['selected_code']&3)-1 and
                active['edge']==(0 if request['selected_code']&4 else 1) and
                not request['published'] and not request['armed'] and not loaded['published'] and not loaded['armed'] and
                pub['published'] and pub['ready'] and pub['armed'] and pub['fresh'] and pub['latest_valid'] and
                all(r['active_code']==request['expected_code'] for r in (loaded,pub)) and
                not any(r.get('violations') for r in (request,loaded,pub)) and pub['max_age_ticks']>0 and
                pub['age_ticks']<=pub['max_age_ticks'] and zero_count is not None and zero_count>=2 and not mapping_errors)
        handovers.append(h)
    fault=next((r for r in rows if r['event']==5),None);shutdown=next((r for r in rows if r['event']==11),None)
    invalid=any(s['sensor_mode']==1 for s in sources);stale=any(s['sensor_mode']==2 for s in sources)
    failure_closed=bool(fault and shutdown and not shutdown['armed'] and not shutdown['published'] and not shutdown['ready'] and evidence.get('native_motor',{}).get('actual_pwm_six_bit_mask')==0)
    if stale:failure_closed=failure_closed and bool(any(r['kind']=='E62_VBUS_ADC_CLOCK_STOP' for r in events)) and fault['age_ticks']>fault['max_age_ticks']
    if invalid:failure_closed=failure_closed and bool(any(r['code']==0 for r in eocs.values())) and not fault['latest_valid']
    positive=bool(len(handovers)>=2 and all(h['complete'] for h in handovers) and not errors)
    constant=bool(len(sources)==1 and not handovers and not errors)
    return {'schema':'e62.source-vbus-handover.v1','status':('FAIL_CLOSED_OBSERVED' if failure_closed and not errors else 'INCOMPLETE_FAIL_CLOSED') if invalid or stale else ('SPECIFIC_SOURCE_HANDOVERS_VERIFIED' if positive else 'CONSTANT_INPUT_CONTROL_OBSERVED' if constant else 'INCOMPLETE_HANDOVER_EVIDENCE'),'sources':sources,'adc_eoc_samples':len(eocs),'adc_reads':len(reads),'source_errors':errors,'handovers':handovers,'fault_entry':fault,'post_shutdown':shutdown,'bounded_journal_missing_ranges':journal.get('missing_sequence_ranges'),'reference_network':'SIM_ONLY1.41V+.02*(VBUS/2+BEMF); VBUS11/160; ADC/DAC3.3V','counter_mapping':'Tick duration derived and checked from local source ZERO timestamp/counter pairs; not host clock','p1_qualified':False,'rotor_synchronized':False,'hardware_qualified':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--log',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=audit(parse(a.log.open()),json.loads(a.evidence.read_text()));a.output.write_text(json.dumps(r,indent=2)+'\n');print(r['status'])
if __name__=='__main__':main()
