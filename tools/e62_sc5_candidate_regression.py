#!/usr/bin/env python3
"""Pinned SC5 integration regression; never substitutes for Issue #3 exact ELF."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE='1452b4ec1575615662d2f9e9e793cbd15fb3e6a381d32bce2fc79fdfff54e1ab'
SOURCE='bb02e4c'
ORIGINAL='05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0'
CASES={'smoke':'e62-native-p0-smoke.json','gentle':'e62-native-p0-gentle.json','direct20':'e62-native-p0-direct20.json','steps':'e62-native-p0-steps.json','ramp20_100ms':'e62-native-p1-ramp20-100ms.json','ramp20_500ms':'e62-native-p1-ramp20-500ms.json'}
PLAN=[(n,None) for n in CASES]+[(n,s) for s,names in [('0:16',('direct20','gentle')),('16:0',('direct20','steps')),('-16:0',('direct20','ramp20_100ms')),('16:20',('direct20','ramp20_500ms'))] for n in names]

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def guard(candidate,original,expected=CANDIDATE):
    if digest(candidate)!=expected or digest(original)!=ORIGINAL:raise ValueError('Pinned SC5 candidate/Original mismatch; no binary substitution')

def invoke(cmd,path,timeout):
    path.with_suffix('.command.json').write_text(json.dumps(cmd,indent=2)+'\n')
    with path.open('w') as log:
        try:return subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=timeout).returncode
        except subprocess.TimeoutExpired:return 124

def main(expected_candidate=CANDIDATE,source=SOURCE,scope='NEW_SC5_EXPERIMENT_NOT_ISSUE3_EXACT_SUITE_OR_ORIGINAL'):
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('candidate','original','qemu','cfg','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--workers',type=int,choices=range(1,5),default=2)
    a=p.parse_args();guard(a.candidate,a.original,expected_candidate)
    if a.output.exists():p.error('Refuse overwriting any evidence directory')
    a.output.mkdir(parents=True)
    inputs={n:{'path':str(getattr(a,n).resolve()),'sha256':digest(getattr(a,n))} for n in ('candidate','original','qemu','cfg')}
    def run(item):
        n,stress=item;prefix=a.output/(n+'-'+(stress or 'nominal').replace(':','_'))
        evidence=prefix.with_suffix('.json');events=prefix.with_suffix('.p0.events.log');verdict=prefix.with_suffix('.p1.json')
        scenario=ROOT/'scenarios'/CASES[n]
        cmd=[sys.executable,str(ROOT/'tests/e62_autonomous_native_motor_probe.py'),'--qemu',str(a.qemu.resolve()),'--elf',str(a.candidate.resolve()),'--experimental-candidate-sha256',expected_candidate,'--cfg-flash',str(a.cfg.resolve()),'--scenario',str(scenario),'--sim-motor-profile','ecx87-kv147','--sim-native-adc-bemf','--differential-sync-start','--wall-timeout-s','600','--artifact',str(evidence.resolve())]
        if stress:cmd+=['--experimental-bemf-robustness='+stress]
        rc=invoke(cmd,prefix.with_suffix('.probe.log'),640)
        ac=invoke([sys.executable,str(ROOT/'tools/native_p1_qualification.py'),'--scenario',str(scenario),'--evidence',str(evidence.resolve()),'--events',str(events.resolve()),'--output',str(verdict.resolve())],prefix.with_suffix('.analyzer.log'),60)
        e=json.loads(evidence.read_text()) if evidence.exists() else {};v=json.loads(verdict.read_text()) if verdict.exists() else {}
        result={'case':n,'stress':stress,'scenario_sha256':digest(scenario),'probe_exit':rc,'analyzer_exit':ac,'strict_status':v.get('status'),'failures':v.get('unwaived_observability_failures',['MISSING_VERDICT']),'direction_changes':v.get('significant_rotor_direction_changes'),'speed_signs':v.get('active_speed_signs_above_50rpm'),'guest_after':e.get('original_guest_after'),'source_frames':e.get('passive_source_dshot_completed'),'evidence':str(evidence),'p1_qualified':v.get('qualified') is True}
        prefix.with_suffix('.result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);return result
    with ThreadPoolExecutor(max_workers=a.workers) as pool:results=list(pool.map(run,PLAN))
    report={'schema':'e62.sc5-candidate-regression.v1','status':'FAILED' if any(not r['p1_qualified'] for r in results) else 'UNEXPECTED_ORIGINAL_IDENTITY_ACCEPTANCE','scope':scope,'source_commit':source,'inputs':inputs,'cases':results,'p1_thresholds_changed':False,'hardware_qualified':False}
    (a.output/'suite.json').write_text(json.dumps(report,indent=2)+'\n');return 1
if __name__=='__main__':raise SystemExit(main())
