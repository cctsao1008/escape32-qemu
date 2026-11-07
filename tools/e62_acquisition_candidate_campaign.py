"""H6/H7: replay pinned controls with one labeled acquisition candidate; no original qualification."""
import argparse,hashlib,json,os,subprocess,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tools.e62_first_sector_campaign import validate_cfg_separation

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('controls','seed-control','elf','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--elf-sha256',required=True);p.add_argument('--qemu-sha256',required=True);p.add_argument('--jobs',type=int,choices=(1,2,3),default=3);a=p.parse_args();root=Path(__file__).resolve().parents[1]
    if sha(a.elf)!=a.elf_sha256:raise SystemExit('Candidate ELF SHA mismatch')
    a.output.mkdir(parents=True,exist_ok=True)
    cases=[('startup-acquisition-angle-30',a.seed_control,None),('startup-acquisition-angle90',a.controls/'startup-firstedge-angle90.command.json',None)]
    cases += [(f'restart-acquisition-coast{c}',a.controls/f'restart-firstedge-coast{c}.command.json',None) for c in (300,1500,3000)]
    cases += [('startup-acquisition-fixed16',a.seed_control,'16:0'),('startup-acquisition-switch16',a.seed_control,'0:16'),('acquisition-clock-loss',a.controls/'adc2k-stale-reference.command.json',None)]
    def run(item):
        name,template,stress=item;parent=json.loads(template.read_text());cmd=parent['command'][:];cmd[0]=sys.executable
        qemu=Path(cmd[cmd.index('--qemu')+1]);cfg=Path(cmd[cmd.index('--cfg-flash')+1]);scenario=Path(cmd[cmd.index('--scenario')+1]);plan=Path(cmd[cmd.index('--source-vbus-plan')+1])
        if sha(qemu)!=a.qemu_sha256:raise ValueError('QEMU hash differs from pinned controls')
        validate_cfg_separation(a.elf,cfg)
        # All non-ELF input files must still match the control's recorded bytes.
        for f in (qemu,cfg,scenario,plan):
            if parent['hashes'].get(str(f.resolve()))!=sha(f):raise ValueError('Control input changed: '+str(f))
        out=a.output.resolve()/(name+'.json');cmd[cmd.index('--elf')+1]=str(a.elf.resolve());cmd[cmd.index('--experimental-candidate-sha256')+1]=a.elf_sha256;cmd[cmd.index('--artifact')+1]=str(out)
        if stress:cmd+=['--experimental-bemf-robustness='+stress]
        meta=dict(command=cmd,control_template=str(template.resolve()),hypothesis='H6 restore spatial-capture acquisition before sync6; H7 sensor-bias/switch-artifact counterexamples. Restart protocol assessed separately at measured second-demand state.',hashes={str(f.resolve()):sha(f) for f in (qemu,cfg,scenario,plan,a.elf)},concurrent_jobs=a.jobs,identity='EXPERIMENTAL_SIM_ONLY_ACQUISITION_CANDIDATE_NOT_ORIGINAL',physics_changed=False,p1_thresholds_changed=False,adc_cadence_hz=1000)
        out.with_suffix('.command.json').write_text(json.dumps(meta,indent=2)+'\n');env=os.environ.copy();env.pop('E62_DSHOT_DIAGNOSTICS',None)
        with out.with_suffix('.stdout.log').open('w') as log:rc=subprocess.run(cmd,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
        meta['probe_rc']=rc;out.with_suffix('.command.json').write_text(json.dumps(meta,indent=2)+'\n');print(name,rc,flush=True)
        if out.exists():
            commands=[['tools.native_p1_qualification','--scenario',str(scenario),'--evidence',str(out),'--events',str(out.with_suffix('.p0.events.log')),'--output',str(out.with_suffix('.strict.json'))]]
            if name.startswith('restart'):
                commands += [['tools.e62_restart_phase_sweep_verdict','--scenario',str(scenario),'--evidence',str(out),'--events',str(out.with_suffix('.p0.events.log')),'--motor-profile','ecx87-kv147','--initial-electrical-degrees','-30','--output',str(out.with_suffix('.restart.json'))]]
            with out.with_suffix('.analyzers.log').open('w') as log:
                for c in commands:subprocess.run([sys.executable,'-m',*c],cwd=root,stdout=log,stderr=subprocess.STDOUT)
        return name,rc
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:results=list(pool.map(run,cases))
    (a.output/'execution-result.json').write_text(json.dumps(dict(probes=results,original_p1_qualified=False,hardware_qualified=False),indent=2)+'\n')
    return bool(any(rc for _,rc in results))
if __name__=='__main__':raise SystemExit(main())
