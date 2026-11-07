"""Pinned diagnostic A/B. No experimental result qualifies Original or changes P1 gates."""
import argparse,hashlib,json,os,subprocess,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('qemu','baseline-elf','candidate-elf','isolation-elf','cfg','output'):p.add_argument('--'+n,type=Path,required=True)
    for n in ('qemu-sha256','baseline-sha256','candidate-sha256','isolation-sha256'):p.add_argument('--'+n,required=True)
    p.add_argument('--jobs',type=int,choices=(1,2,3,4),default=3);p.add_argument('--family',choices=('startup','restart','invalid'),action='append')
    a=p.parse_args();root=Path(__file__).resolve().parents[1];a.output.mkdir(parents=True,exist_ok=True)
    for f,h in ((a.qemu,a.qemu_sha256),(a.baseline_elf,a.baseline_sha256),(a.candidate_elf,a.candidate_sha256),(a.isolation_elf,a.isolation_sha256)):
        if sha(f)!=h:raise SystemExit('Input hash mismatch: '+str(f))
    items=[];families=a.family or ('startup','restart','invalid')
    if 'startup' in families:
        for angle in (-30,90):
            for name,elf in (('baseline',a.baseline_elf),('firstedge',a.candidate_elf)):
                items.append((f'startup-{name}-angle{angle}',elf,angle,root/'scenarios/e62-v4/handover-drive.json','constant','1499:1545',True,'H1 acceptance-only; H2 initial-pose sensitivity'))
    if 'restart' in families:
        for coast,scenario in ((300,'short300'),(1500,'reacquire'),(3000,'long3000')):
            for name,elf in (('baseline',a.baseline_elf),('firstedge',a.candidate_elf)):
                onset=3000+coast
                items.append((f'restart-{name}-coast{coast}',elf,-30,root/f'scenarios/e62-experimental-two-demand-coast-{scenario}.json','constant',f'{onset-1}:{onset+45}',False,'H3 restart assessed independently at actual second-demand rotor state'))
    if 'invalid' in families:
        for plan in ('constant','invalid-reference','stale-reference'):
            items.append((f'adc2k-{plan}',a.isolation_elf,-30,root/'scenarios/e62-v4/handover-drive.json',plan,'1839:1845',False,'H4 native invalid publication while old sample is fresh; 2kHz SIM_ONLY acquisition, age32 unchanged'))
    def run(item):
        name,elf,angle,scenario,plan,focus,decisions,hyp=item;out=a.output.resolve()/(name+'.json');vbus=root/'scenarios/e62-v4'/('vbus-'+plan+'.csv')
        cmd=[sys.executable,str(root/'tests/e62_autonomous_native_motor_probe.py'),'--qemu',str(a.qemu.resolve()),'--elf',str(elf.resolve()),'--experimental-candidate-sha256',sha(elf),'--cfg-flash',str(a.cfg.resolve()),'--scenario',str(scenario),'--sim-motor-profile','ecx87-kv147','--sim-initial-electrical-degrees',str(angle),'--sim-native-adc-bemf','--reference-diagnostics','--source-vbus-plan',str(vbus),'--switch-focus-window-ms',focus,'--differential-sync-start','--wall-timeout-s','900','--artifact',str(out)]
        if decisions:cmd+=['--issue5-bemf-diag']
        meta=dict(command=cmd,hypothesis=hyp,hashes={str(f.resolve()):sha(f) for f in (a.qemu,elf,a.cfg,scenario,vbus)},concurrent_jobs=a.jobs,firmware_identity='EXPERIMENTAL_NOT_ORIGINAL_OR_PRODUCTION_ROOT_FIXES',p1_thresholds_changed=False,physics_changed=False)
        out.with_suffix('.command.json').write_text(json.dumps(meta,indent=2)+'\n');env=os.environ.copy();env.pop('E62_DSHOT_DIAGNOSTICS',None)
        with out.with_suffix('.stdout.log').open('w') as log:rc=subprocess.run(cmd,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
        meta['probe_rc']=rc;out.with_suffix('.command.json').write_text(json.dumps(meta,indent=2)+'\n');print(name,rc,flush=True)
        if out.exists():
            analyzers=[['-m','tools.native_p1_qualification','--scenario',str(scenario),'--evidence',str(out),'--events',str(out.with_suffix('.p0.events.log')),'--output',str(out.with_suffix('.strict.json'))]]
            if name.startswith('adc2k'):
                analyzers+=[['-m','tools.e62_vbus_handover_audit','--log',str(out.with_suffix('.qemu.log')),'--evidence',str(out),'--output',str(out.with_suffix('.reference-flow.json'))]]
            if name.startswith('restart'):
                analyzers+=[['-m','tools.e62_restart_phase_sweep_verdict','--scenario',str(scenario),'--evidence',str(out),'--events',str(out.with_suffix('.p0.events.log')),'--motor-profile','ecx87-kv147','--initial-electrical-degrees',str(angle),'--output',str(out.with_suffix('.restart.json'))]]
            with out.with_suffix('.analyzers.log').open('w') as log:
                for argv in analyzers:subprocess.run([sys.executable,*argv],cwd=root,stdout=log,stderr=subprocess.STDOUT)
        return name,rc
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:result=list(pool.map(run,items))
    (a.output/'campaign-result.json').write_text(json.dumps(dict(probes=result,p1_qualified=False,hardware_qualified=False),indent=2)+'\n')
    return 1 if any(rc for _,rc in result) else 0
if __name__=='__main__':raise SystemExit(main())
