#!/usr/bin/env python3
"""Independent E62 simulated external-fault evidence qualification."""
import json
from pathlib import Path
import sys

MASKS={'nfault':0x20000,'oc-u':0x40000,'oc-v':0x40000,'oc-w':0x40000}
ORDER=['nfault','oc-u','oc-v','oc-w']

def verify_case(name,d):
    mask=MASKS[name]
    issues=[]
    if d.get('fault')!=name:issues.append('wrong_fault_identity')
    if d.get('irq_ipsr')!=44:issues.append('not_original_mcpwm4_irq')
    if d.get('shutdown_pc_hit')!=d.get('shutdown_pc') or not isinstance(
        d.get('shutdown_pc_hit'),int):
        issues.append('no_source_owned_shutdown_pc')
    if not (d.get('tzflags',0) & mask):issues.append('no_physical_ost_trip')
    if not (d.get('interrupt_flags',0)&4):issues.append('no_pwm_irq_flag')
    if d.get('gate_inactive') is not True:issues.append('gate_not_inactive')
    return issues

def verify_all(data):
    issues=[]
    passed=[]
    for name in ORDER:
        d=data.get(name)
        if not isinstance(d,dict):
            issues.append(name+':missing_artifact')
            continue
        errs=verify_case(name,d)
        if errs:issues.extend(f'{name}:{x}' for x in errs)
        else:passed.append(name)
    return {
        'status':'PASS_SIM_ONLY_EXTERNAL_FAULT_IRQ_SHUTDOWN_ONLY' if not issues
                 else 'FAIL_INDEPENDENT_FAULT_GATE',
        'independent_cases_passed':passed,
        'issues':issues,
        'scope':'MODEL_ONLY_NATIVE_NEUTRAL_NOT_MOTOR_RUNNING',
        'signal_loss_watchdog_recovery':'OPEN_NOT_QUALIFIED',
        'invalid_dshot_crc_rejection':'OPEN_NOT_QUALIFIED',
        'real_power_stage':'NOT_QUALIFIED',
    }

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--artifacts-dir',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    records={}
    for name in ORDER:
        path=a.artifacts_dir/('e62-safety-'+name+'.json')
        if path.is_file():records[name]=json.loads(path.read_text())
    result=verify_all(records)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print('E62_SAFETY_NEGATIVE_QUALIFICATION '+json.dumps(result,sort_keys=True))
    return 0 if not result['issues'] else 1

if __name__=='__main__':sys.exit(main())
