"""Offline evidence of actual Guest-read phase samples; never supplies rotor feedback."""
import argparse,json
from pathlib import Path
from tools.e62_issue5_cap1_timer_audit import parse

def observe(events,demand_vns,window_ns=20_000_000):
    eocs={};epochs={}
    for e in events:
        if e['vns']>=demand_vns:break
        if e['kind']=='ADC_PHASE_EOC':eocs[(e['a'],e['e'])]=e
        if e['kind']=='ADC_PHASE_READ' and demand_vns-window_ns<=e['vns']:
            source=eocs.get((e['a'],e['e']))
            if source and source['b']==e['b'] and source['seq']<e['seq'] and 0<=e['a']<3:
                epochs.setdefault(e['e'],{})[e['a']]=(source,e)
    rows=[]
    for epoch,phases in sorted(epochs.items()):
        if set(phases)!={0,1,2}:continue
        source=[phases[i][0] for i in range(3)];reads=[phases[i][1] for i in range(3)]
        codes=[e['b'] for e in reads]
        if not all(0<=v<=4095 for v in codes):continue
        hi=max(codes);lo=min(codes)
        rows.append(dict(epoch=epoch,codes=codes,source_eoc_vns=[e['vns'] for e in source],source_read_vns=[e['vns'] for e in reads],sample_age_ns=demand_vns-max(e['vns'] for e in source),all_source_gates_off=all(e['f']==0 for e in source),spread_codes=hi-lo,unique_extrema=codes.count(hi)==1 and codes.count(lo)==1))
    last=rows[-1] if rows else None
    return dict(status='INCOMPLETE',reason='MISSING_COHERENT_GUEST_READ_TRIPLE' if not last else 'TIED_OR_SINGLE_CODE_PHASE_EVIDENCE' if not last['unique_extrema'] or last['spread_codes']<=1 else 'DIRECTION_NOT_PROVEN_BY_INSTANTANEOUS_VECTOR',last_guest_read_sample=last,coherent_epochs_in_window=len(rows),distinct_quantized_vectors_in_window=len({tuple(r['codes']) for r in rows}),sampled_vectors=rows,direction_proven=False,stationary_proven=False,model_rotor_used_as_input=False,phase_voltage_limit='Existing SIM_ONLY ADC model publishes BEMF codes even for powered phases; physical terminal-voltage/blanking qualification remains separate.')
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--events',type=Path,required=True);p.add_argument('--demand-vns',type=int,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=observe(parse(a.events.read_text()),a.demand_vns);a.output.write_text(json.dumps(r,indent=2)+'\n');print(r['reason'])
if __name__=='__main__':main()
