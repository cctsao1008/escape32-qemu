#!/usr/bin/env python3
"""Read-only bench/model error report. Never fits physics or grants approval."""
import argparse
import hashlib
import json
import math
from pathlib import Path

METRICS=('voltage_v','current_a','rpm')


def correlate(measured, predicted):
    if not isinstance(measured,dict) or not isinstance(predicted,dict):
        raise ValueError('Measurement and prediction must be objects')
    if measured.get('origin')!='PHYSICAL_BENCH' or predicted.get('origin')!='SIM_ONLY':
        raise ValueError('Physical measurement and SIM_ONLY prediction provenance required')
    for key in ('sensor_calibration','fixture_identity','motor_id','propeller_id','clock_synchronization'):
        if not isinstance(measured.get(key),str) or not measured[key]:
            raise ValueError('Missing measurement provenance: '+key)
    if not isinstance(predicted.get('effective_parameters'),dict) or not predicted['effective_parameters']:
        raise ValueError('Effective simulation parameter readback required')
    uncertainty=measured['uncertainty']
    if any(type(uncertainty[k]) not in (int,float) or not math.isfinite(uncertainty[k]) or uncertainty[k]<=0 for k in METRICS):
        raise ValueError('Positive finite measurement uncertainties required')
    a,b=measured['samples'],predicted['samples']
    if len(a)<2 or len(a)!=len(b):raise ValueError('Matched sample coverage required')
    previous=-1;errors={k:[] for k in METRICS}
    for x,y in zip(a,b):
        if (type(x['t_ns']) is not int or type(y['t_ns']) is not int or x['t_ns']<=previous or
            x['t_ns']!=y['t_ns']):raise ValueError('Exact monotonic aligned timestamps required; no interpolation')
        previous=x['t_ns']
        for k in METRICS:
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in (x[k],y[k])):
                raise ValueError('Finite physical values required')
            errors[k].append(y[k]-x[k])
    return dict(schema='e62.model-correlation.v1',status='ERRORS_REPORTED_NOT_QUALIFIED',
        sample_count=len(a),error_bands={k:dict(rmse=math.sqrt(sum(x*x for x in v)/len(v)),
            minimum_signed_error=min(v),maximum_signed_error=max(v),
            max_absolute_error=max(abs(x) for x in v),measurement_uncertainty=uncertainty[k],
            outside_measurement_uncertainty=sum(abs(x)>uncertainty[k] for x in v))
            for k,v in errors.items()},
        simulation_effective_parameters=predicted['effective_parameters'],
        hardware_qualified=False,model_calibrated=False,porting_complete=False)


def load_pair(manifest):
    m=json.loads(manifest.read_text());docs=[]
    for key in ('measurement','prediction'):
        p=manifest.parent/m[key]['path'];raw=p.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=m[key]['sha256']:raise ValueError('SHA mismatch: '+key)
        docs.append(json.loads(raw))
    return correlate(*docs)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    try:result=load_pair(a.manifest);code=0
    except OSError as exc:
        result=dict(schema='e62.model-correlation.v1',status='BLOCKED_EXTERNAL',error=str(exc),hardware_qualified=False,model_calibrated=False);code=2
    except (ValueError,KeyError,TypeError) as exc:
        result=dict(schema='e62.model-correlation.v1',status='INCOMPLETE',error=str(exc),hardware_qualified=False,model_calibrated=False);code=1
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');return code


if __name__=='__main__':raise SystemExit(main())
