"""Forensic triage of G13B3M SIM_ONLY rotor trajectory failures.

This does not override native_extended_run_gate.py or convert source
BEMF scripted Functional PASS into physics or direction PASS.
"""
import json

def _find(source, key):
    found=[]
    def scan(x):
        if isinstance(x,dict):
            if key in x:found.append(x[key])
            for v in x.values():scan(v)
        elif isinstance(x,list):
            for v in x:scan(v)
    scan(source)
    return found

def diagnose(native_result):
    profiles=_find(native_result,'electromagnetic_power_ratio_pe_over_pm')
    integrators=_find(native_result,'integrator')
    reversals=_find(native_result,'significant_direction_reversals')
    nonreciprocal=any(isinstance(x,(float,int)) and abs(x-1)>1e-6 for x in profiles)
    projected=any(isinstance(s,str) and 'RESET_CURRENT_AT_COMMUTATION' in s
                  for s in integrators)
    signs=max((x for x in reversals if type(x) is int),default=None)
    return {
        'status':'OPEN_STRICT_ROTOR_TRAJECTORY_NOT_PROVED',
        'sim_only_significant_direction_reversals':signs,
        'motor_kt_ke_power_ratios':profiles,
        'nonreciprocal_legacy_model':nonreciprocal,
        'commutation_resets_inductive_current':projected,
        'potential_model_issues':[
            x for flag,x in (
                (nonreciprocal,'KT_KE_NONRECIPROCAL_ENERGY_IDENTITY'),
                (projected,'CURRENT_DISCONTINUITY_AT_COMMUTATION'))
            if flag],
        'scope':'FORENSIC_UNCALIBRATED_SIM_ONLY_NOT_CONFIRMED_CAUSAL_ROOT',
        'strict_gate':'UNCHANGED_FAIL_UNLESS_EXTENDED_NATIVE_GATE_PASSES',
    }

def main():
    import argparse
    from pathlib import Path
    p=argparse.ArgumentParser()
    p.add_argument('--native-result',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    report=diagnose(json.loads(a.native_result.read_text()))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    print('E62_G13B3M_ROTOR_CAUSAL_DIAGNOSTIC '+json.dumps(report,sort_keys=True))
    return 0

if __name__=='__main__':raise SystemExit(main())
