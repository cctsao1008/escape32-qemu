#!/usr/bin/env python3
"""Execute Issue #3's exact 14 cases; refuse binary substitutions and waivers."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ELF_SHA = '5b90b200429333cef82b982b7a7f845f31fb885c7ea63fc7e783c75232fac8d1'
ORIGINAL_SHA = '05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0'
GROUPS = [('off', ('smoke','gentle')), ('off', ('direct20','steps')),
          ('off', ('ramp20_100ms','ramp20_500ms')), ('0:16', ('direct20','gentle')),
          ('16:0', ('direct20','steps')), ('-16:0', ('direct20','ramp20_100ms')),
          ('16:20', ('direct20','ramp20_500ms'))]


def plan():
    return [dict(case=c, stress=s) for s, cases in GROUPS for c in cases]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_inputs(candidate, original):
    if digest(candidate) != ELF_SHA or digest(original) != ORIGINAL_SHA:
        raise ValueError('Exact Issue #3 candidate or Original SHA mismatch; no substitute executed')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('candidate','original','qemu','cfg','output'):
        p.add_argument('--'+k, required=True, type=Path)
    p.add_argument('--workers',type=int,choices=range(1,5),default=2)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    report=dict(schema='e62.exact-cmpss-suite.v1',expected_elf_sha256=ELF_SHA,
                original_p1_qualified=False,hardware_qualified=False,cases=plan())
    try:
        check_inputs(a.candidate,a.original)
        report.update(qemu_sha256=digest(a.qemu),cfg_sha256=digest(a.cfg))
    except (OSError,ValueError) as exc:
        report.update(status='BLOCKED_EXTERNAL',executed=0,error=str(exc))
        for row in report['cases']:row['status']='BLOCKED_EXTERNAL'
        (a.output/'suite.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report));return 2
    def run(group):
        index,(stress,cases)=group;out=a.output/f'group-{index:02d}'
        out.mkdir(exist_ok=True)
        cmd=[sys.executable,str(ROOT/'tools/experimental_e62_source_bemf_filter_matrix.py'),
             '--qemu',str(a.qemu.resolve()),'--candidate',str(a.candidate.resolve()),
             '--original',str(a.original.resolve()),'--cfg',str(a.cfg.resolve()),
             '--stress='+stress,'--output',str(out.resolve()),'--wall-timeout-s','600']
        for case in cases:cmd+=['--case',case]
        (out/'command.json').write_text(json.dumps(cmd,indent=2)+'\n')
        with (out/'runner.log').open('w') as log:
            result=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        summaries=list(out.glob('*summary*.json'))
        return dict(group=index,stress=stress,cases=cases,exit_code=result.returncode,
                    summaries=[str(x.relative_to(a.output)) for x in summaries])
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        groups=list(pool.map(run,enumerate(GROUPS)))
    report.update(status='PASS_EXPERIMENT_ONLY' if all(x['exit_code']==0 for x in groups)
                  else 'FAILED',groups=groups)
    report['executed_groups']=len(groups)
    # Group launch is not evidence that every native case completed. Raw case
    # summaries and their individual statuses remain authoritative.
    report['case_completion_requires_individual_evidence']=True
    (a.output/'suite.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report));return 0 if report['status']=='PASS_EXPERIMENT_ONLY' else 1


if __name__=='__main__':raise SystemExit(main())
