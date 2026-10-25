#!/usr/bin/env python3
"""Repeat full original-Guest Functional T01 on the SAME host.

Reproducibility benchmark only. Does NOT infer speedup against any other
version or qualify a physical motor. Does not change QEMU or Guest.
"""
import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

def analyze(trials):
    if not trials or any(t['returncode'] != 0 or
        t['status']!='PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL' for t in trials):
        return {'status':'FAIL_INVALID_FUNCTIONAL_BENCHMARK',
                'reason':'A failed functional run cannot be a speed sample'}
    values=[x['wall_elapsed_s'] for x in trials]
    return {'status':'PASS_SAME_VERSION_REPEATABILITY_ONLY',
            'count':len(values),'mean_wall_s':statistics.mean(values),
            'median_wall_s':statistics.median(values),
            'min_wall_s':min(values),'max_wall_s':max(values),
            'stddev_wall_s':statistics.stdev(values) if len(values)>1 else None,
            'speedup_against_g13b6':'OPEN_NO_SAME_HOST_MATCHED_BASELINE',
            'motor_physics':'NOT_QUALIFIED'}

def main():
    ap=argparse.ArgumentParser()
    for name in ('qemu','elf','cfg-flash','plan'):
        ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--repeats',type=int,default=3)
    ap.add_argument('--output-dir',type=Path,default=Path('artifacts/perf'))
    a=ap.parse_args()
    if not 2<=a.repeats<=5:
        ap.error('Require 2-5 repeats for same-host comparison')
    for p in (a.qemu,a.elf,a.cfg_flash,a.plan):
        if not p.is_file():ap.error('Missing file '+str(p))
    a.output_dir.mkdir(parents=True,exist_ok=True)
    trials=[]
    runner=Path(__file__).resolve().parents[2]/'tests/functional_dshot_sitl.py'
    for i in range(a.repeats):
        artifact=a.output_dir/f't01-trial-{i+1}.json'
        log=a.output_dir/f't01-trial-{i+1}.log'
        cmd=[sys.executable,str(runner),'--autonomous',
             '--autonomous-telemetry-interval-ms','200',
             '--qemu',str(a.qemu.resolve()),
             '--elf',str(a.elf.resolve()),
             '--cfg-flash',str(a.cfg_flash.resolve()),
             '--plan',str(a.plan.resolve()),'--id','T01',
             '--artifact',str(artifact)]
        start=time.monotonic()
        with log.open('wb') as out:
            result=subprocess.run(cmd,stdout=out,stderr=subprocess.STDOUT,
                                  check=False,timeout=1200)
        elapsed=time.monotonic()-start
        d=json.loads(artifact.read_text()) if artifact.is_file() else {}
        row={'iteration':i+1,'wall_elapsed_s':elapsed,
             'returncode':result.returncode,'status':d.get('status','MISSING'),
             'original_crc_delta':d.get('autonomous',{}).get('valid_crc_feed_delta'),
             'issues':d.get('issues',['no_artifact'])}
        trials.append(row)
        print('E62_REPEATED_T01_TRIAL '+json.dumps(row,sort_keys=True),flush=True)
    summary={'scope':'SAME_HOST_SAME_COMMIT_REPEATABILITY_NOT_CROSS_HOST_SPEEDUP',
             'trials':trials,'result':analyze(trials)}
    (a.output_dir/'summary.json').write_text(
        json.dumps(summary,indent=2)+'\n')
    print('E62_T01_PERFORMANCE_REPETITIONS '+json.dumps(summary['result'],sort_keys=True))
    return 0 if summary['result']['status'].startswith('PASS_') else 1

if __name__=='__main__':
    sys.exit(main())
