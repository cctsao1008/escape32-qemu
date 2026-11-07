"""Incremental H12: failed restart A/B with equal ADC observer and explicit new identities."""
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from tools.e62_first_sector_campaign import validate_cfg_separation
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnostic-kind',choices=('rate','coast'),default='rate')
    parser.add_argument('--screen-coast',type=int,choices=(300,1500,3000),default=1500)
    parser.add_argument('--build-prefix',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--selection',choices=('screen','remaining','coasts','candidate-remaining','controls'),required=True)
    parser.add_argument('--jobs',type=int,choices=(1,2,3),default=3)
    parser.add_argument('--include-startup-stress',action='store_true')
    opt=parser.parse_args();output=opt.output.resolve();output.mkdir(parents=True,exist_ok=True)
    cases=[(f'{mode}-coast{c}',mode,f'restart-prompt-coast{c}',None) for mode in ('candidate','control') for c in (300,1500,3000)]
    if opt.selection=='screen':cases=[c for c in cases if c[0]==f'candidate-coast{opt.screen_coast}']
    if opt.selection=='remaining':cases=[c for c in cases if c[0]!=f'candidate-coast{opt.screen_coast}']
    if opt.selection=='candidate-remaining':cases=[c for c in cases if c[1]=='candidate' and c[0]!=f'candidate-coast{opt.screen_coast}']
    if opt.selection=='controls':cases=[c for c in cases if c[1]=='control']
    if opt.include_startup_stress:cases += [('candidate-angle90','candidate','startup-prompt-angle90',None),('candidate-offset-plus16','candidate','startup-prompt-angle-30','16:0'),('candidate-offset-minus16','candidate','startup-prompt-angle-30','-16:0')]
    def run(case):
        name,mode,template_name,stress=case
        build_path=ROOT/f'artifacts/e62-v6/{opt.build_prefix}-{mode}.build-provenance.json';build=json.loads(build_path.read_text());
        if build.get('build_rc')!=0 or 'elf_path' not in build:raise ValueError('Required experimental firmware build is incomplete or failed: '+str(build_path))
        elf=Path(build['elf_path'])
        assert sha(elf)==build['elf_sha256']
        template=ROOT/f'artifacts/e62-v5/prompt-campaign/{template_name}.command.json';parent=json.loads(template.read_text());cmd=parent['command'][:];cmd[0]=sys.executable
        for option in ('--qemu','--cfg-flash','--scenario','--source-vbus-plan'):
            f=Path(cmd[cmd.index(option)+1]);assert parent['hashes'][str(f.resolve())]==sha(f)
        qemu=Path(cmd[cmd.index('--qemu')+1]);assert sha(qemu)=='6f99975e319ada16af98050c66b1ee39fef690d8dca16ec08a6c59560f7faef8'
        validate_cfg_separation(elf,Path(cmd[cmd.index('--cfg-flash')+1]))
        target=output/(name+'.json');
        if target.exists():raise ValueError('Refusing to overwrite existing evidence: '+str(target))
        cmd[cmd.index('--elf')+1]=str(elf);cmd[cmd.index('--experimental-candidate-sha256')+1]=build['elf_sha256'];cmd[cmd.index('--artifact')+1]=str(target);cmd+=['--coast-phase-diagnostics' if opt.diagnostic_kind=='coast' else '--restart-rate-diagnostics']
        if stress:cmd+=['--experimental-bemf-robustness='+stress]
        meta=dict(command=cmd,selection='Previously failed coast with discriminating H12 correction/control;90/offset dependency impacted by ADC-observer code and new ELF. No unchanged PASS rerun.',hypothesis=('H13 compare same coast ADC phase-sequence observer: retain oldstep versus acquired upcoming sector and first two actual crossings. No model angle is Guest input.' if opt.diagnostic_kind=='coast' else 'H12 first partial capture versus fresh apparent phase-rate seed/refusal.'),identity=('EXPERIMENTAL_H13_' if opt.diagnostic_kind=='coast' else 'EXPERIMENTAL_H12_')+mode.upper()+'_NOT_ORIGINAL_OR_PRODUCTION_ROOT_FIXES',build=build,template=str(template),template_sha256=sha(template),hashes={str(Path(cmd[cmd.index(o)+1]).resolve()):sha(Path(cmd[cmd.index(o)+1])) for o in ('--qemu','--elf','--cfg-flash','--scenario','--source-vbus-plan')},test_implementation_sha256=sha(ROOT/'tests/e62_autonomous_native_motor_probe.py'),harness_sources={n:sha(ROOT/n) for n in ('tools/e62_coast_acquire_diag.py','tools/e62_restart_seed_diag.py','tools/native_p1_qualification.py','tools/e62_restart_phase_sweep_verdict.py','tools/e62_second_demand_oracle.py')},concurrent_jobs=opt.jobs,model_physics_changed=False,p1_thresholds_changed=False)
        target.with_suffix('.command.json').write_text(json.dumps(meta,indent=2)+'\n')
        env=os.environ.copy();env.pop('E62_BEMF_ACQUISITION_DIAGNOSTICS',None);env.pop('E62_DSHOT_DIAGNOSTICS',None)
        with target.with_suffix('.stdout.log').open('w') as log:rc=subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
        meta['probe_rc']=rc;target.with_suffix('.command.json').write_text(json.dumps(meta,indent=2)+'\n')
        if target.exists():
            args=[['tools.native_p1_qualification','--scenario',cmd[cmd.index('--scenario')+1],'--evidence',str(target),'--events',str(target.with_suffix('.p0.events.log')),'--output',str(target.with_suffix('.strict.json'))]]
            if 'coast' in name:args += [['tools.e62_restart_phase_sweep_verdict','--scenario',cmd[cmd.index('--scenario')+1],'--evidence',str(target),'--events',str(target.with_suffix('.p0.events.log')),'--motor-profile','ecx87-kv147','--initial-electrical-degrees','-30','--output',str(target.with_suffix('.restart.json'))]]
            with target.with_suffix('.analyzers.log').open('w') as log:
                for a in args:subprocess.run([sys.executable,'-m',*a],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        print(name,rc,flush=True);return (name,rc)
    with ThreadPoolExecutor(max_workers=opt.jobs) as pool:results=list(pool.map(run,cases))
    (output/'execution-result.json').write_text(json.dumps(dict(probes=results,qualification=False),indent=2)+'\n')
    return any(rc for _,rc in results)
if __name__=='__main__':raise SystemExit(main())
