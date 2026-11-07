"""Read-only native comparator point audit; flags and motor state are source observations, not inferred feedback."""
import argparse,json,math,re
from pathlib import Path
from tools.e62_issue5_cap1_timer_audit import parse
FLOATS={'theta','omega','ia','ib','ic','torque'}
def analyze(text):
    events=parse(text);byseq={e['seq']:e for e in events};points=[]
    for line in text.splitlines():
        if 'E62_BEMF_ACQ ' not in line:continue
        raw=dict(re.findall(r'(\w+)=([^ ]+)',line.split('E62_BEMF_ACQ ',1)[1].strip()))
        r={k:float(v) if k in FLOATS else int(v) for k,v in raw.items()}
        required=FLOATS|{'vns','source_seq','phase','level','ecctl0','ecctl1','ecctl2','eceint','capture_index','frozen','pwm_counter','pwm_period','motor_sample_vns','motor_active','mask','gate'}
        if required-r.keys() or not all(math.isfinite(r[k]) for k in FLOATS):raise ValueError('Incomplete/nonfinite source point')
        e=byseq.get(r['source_seq'])
        if not e or e['kind']!='CMP_FILTER' or e['a']!=r['phase'] or e['b']!=r['level'] or e['vns']>r['vns'] or not 0<=r['phase']<3 or r['motor_sample_vns']>r['vns']:raise ValueError('Point does not match its source event/state epoch')
        selected=(not bool(r['level']))==bool(r['ecctl1']&(1<<(2*r['capture_index'])))
        live=bool(r['motor_active'] and r['gate'] and (r['ecctl0']&127)==45 and r['ecctl2']&16 and not(r['ecctl2']&512) and not r['frozen'] and r['capture_index']==0)
        enabled=bool(r['ecctl1']&256 and r['eceint']&2)
        nxt=byseq.get(r['source_seq']+1)
        actual=bool(nxt and nxt['kind']=='CAP1' and nxt['b']==r['phase'] and nxt['vns']>=e['vns'])
        label=('UNSELECTED_POLARITY' if not selected else 'INACTIVE_OR_UNROUTED' if not live else 'CAPTURE_DISABLED_AT_MATCHING_TRANSITION' if not enabled else 'REAL_CAP1_SOURCE_OBSERVED' if actual else 'INCOMPLETE_EXPECTED_CAPTURE_CONTEXT')
        points.append(dict(source=r,source_cmp=e,classification=label,real_cap1=nxt if actual else None,motor_sample_age_ns=r['vns']-r['motor_sample_vns'],source_observation_after_cmp_ns=r['vns']-e['vns'],rpm=r['omega']*60/(2*math.pi),electrical_degrees_unwrapped=math.degrees(r['theta']),floating_phase_sine=math.sin(r['theta']+(0,-2*math.pi/3,2*math.pi/3)[r['phase']]),provenance='SOURCE_OBSERVED_READ_ONLY_NO_PLANT_ADVANCE'))
    if not points:raise ValueError('Missing opt-in source acquisition points')
    return dict(schema='e62.bemf-source-acquisition.v1',points=points,matching_disabled_points=[p for p in points if p['classification']=='CAPTURE_DISABLED_AT_MATCHING_TRANSITION'],incomplete_enabled_points=[p for p in points if p['classification']=='INCOMPLETE_EXPECTED_CAPTURE_CONTEXT'],firmware_private_cause='NOT_OBSERVED_BY_THIS_TOOL; correlate source/code/register reproduction',p1_qualified=False,hardware_qualified=False)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--log',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=analyze(a.log.read_text());a.output.write_text(json.dumps(r,indent=2)+'\n');print('matching_disabled_points',len(r['matching_disabled_points']))
if __name__=='__main__':main()
