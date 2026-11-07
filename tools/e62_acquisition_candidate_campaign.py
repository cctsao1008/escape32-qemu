"""H6/H7: replay pinned controls with one labeled acquisition candidate; no original qualification."""
import argparse,hashlib,json,os,subprocess,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tools.e62_first_sector_campaign import validate_cfg_separation

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('controls','seed-control','elf','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--integration-manifest',type=Path);p.add_argument('--parent-policy-id',choices=('acquisition','estimator','continuity','prompt'),default='acquisition');p.add_argument('--parent-campaign',type=Path);p.add_argument('--policy-id',choices=('acquisition','estimator','continuity','prompt'),default='acquisition');p.add_argument('--elf-sha256',required=True);p.add_argument('--qemu-sha256',required=True);p.add_argument('--jobs',type=int,choices=(1,2,3),default=3);a=p.parse_args();root=Path(__file__).resolve().parents[1]
    if sha(a.elf)!=a.elf_sha256:raise SystemExit('Candidate ELF SHA mismatch')
    a.output.mkdir(parents=True,exist_ok=True)
    cases=[('startup-acquisition-angle-30',a.seed_control,None),('startup-acquisition-angle90',a.controls/'startup-firstedge-angle90.command.json',None)]
    cases += [(f'restart-acquisition-coast{c}',a.controls/f'restart-firstedge-coast{c}.command.json',None) for c in (300,1500,3000)]
    cases += [('startup-acquisition-fixed16',a.seed_control,'16:0'),('startup-acquisition-switch16',a.seed_control,'0:16'),('acquisition-clock-loss',a.controls/'adc2k-stale-reference.command.json',None)]
    if a.parent_campaign:cases=[(n,a.parent_campaign/(n.replace('acquisition',a.parent_policy_id)+'.command.json'),None) for n,_,_ in cases]
    extra_specs={}
    if a.integration_manifest:
        for spec in json.loads(a.integration_manifest.read_text())['cases']:
            extra_specs[spec['name']]=spec;cases.append((spec['name'],Path(spec['control_template']),None))
    def run(item):
        name,template,stress=item;spec=extra_specs.get(name);name=name if spec else name.replace('acquisition',a.policy_id);parent=json.loads(template.read_text());cmd=parent['command'][:];cmd[0]=sys.executable
        qemu=Path(cmd[cmd.index('--qemu')+1]);cfg=Path(cmd[cmd.index('--cfg-flash')+1]);scenario=Path(cmd[cmd.index('--scenario')+1]);plan=Path(cmd[cmd.index('--source-vbus-plan')+1])
        elf=a.elf;expected_elf=a.elf_sha256;expected_qemu=a.qemu_sha256
        if spec:
            build=json.loads(Path(spec['build_provenance']).read_text());elf=Path(build['elf_path']);expected_elf=build['elf_sha256'];expected_qemu=spec.get('qemu_sha256',expected_qemu)
        if sha(elf)!=expected_elf:raise ValueError('Integration ELF hash mismatch')
        if sha(qemu)!=expected_qemu:raise ValueError('QEMU hash differs from pinned controls')
        validate_cfg_separation(elf,cfg)
        # All non-ELF input files must still match the control's recorded bytes.
        for f in (qemu,cfg,scenario,plan):
            recorded=parent['hashes'].get(str(f.resolve()))
            if recorded is None:
                try:recorded=parent['hashes'].get(str(f.resolve().relative_to(root)))
                except ValueError:pass
            if recorded!=sha(f):raise ValueError('Control input changed or unrecorded: '+str(f))
        out=a.output.resolve()/(name+'.json');cmd[cmd.index('--elf')+1]=str(elf.resolve());cmd[cmd.index('--experimental-candidate-sha256')+1]=expected_elf;cmd[cmd.index('--artifact')+1]=str(out)
        if stress:cmd+=['--experimental-bemf-robustness='+stress]
        meta=dict(command=cmd,control_template=str(template.resolve()),hypothesis={'estimator':'H8 measured acquisition intervals, then original locked filter; restart assessed separately.', 'acquisition':'H6 acquisition window; H7 sensor-artifact negatives; restart assessed separately.', 'continuity':'H9 preserve capture through equivalent fresh reference publication; fail closed at original expiry.', 'prompt':'H10 process completed ADC reference in existing PendSV without changing ADC cadence; combined with H8/H9, not a single-variable controller experiment.'}[a.policy_id],hashes={str(f.resolve()):sha(f) for f in (qemu,cfg,scenario,plan,elf)},concurrent_jobs=a.jobs,identity='EXPERIMENTAL_SIM_ONLY_'+a.policy_id.upper()+'_CANDIDATE_NOT_ORIGINAL',physics_changed=False,p1_thresholds_changed=False,adc_cadence_hz=spec.get('adc_cadence_hz',1000) if spec else 1000)
        out.with_suffix('.command.json').write_text(json.dumps(meta,indent=2)+'\n');env=os.environ.copy();env.pop('E62_DSHOT_DIAGNOSTICS',None);env.pop('E62_BEMF_ACQUISITION_DIAGNOSTICS',None)
        if spec:env.update(spec.get('environment',{}));meta['environment']=spec.get('environment',{});meta['hypothesis']=spec['hypothesis'];meta['identity']=spec['identity']
        out.with_suffix('.command.json').write_text(json.dumps(meta,indent=2)+'\n')
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
