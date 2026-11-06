"""Execute explicitly pinned SIM_ONLY source-VBUS cases; never a P1 qualification runner."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('qemu','elf','cfg-flash','output-dir'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('qemu-sha256','elf-sha256','firmware-source-commit'):p.add_argument('--'+name,required=True)
    p.add_argument('--case',choices=('constant','up-down','invalid-reference','stale-reference'),action='append')
    a=p.parse_args();root=Path(__file__).resolve().parents[1]
    for path,expected in ((a.qemu,a.qemu_sha256),(a.elf,a.elf_sha256)):
        if sha(path)!=expected:raise SystemExit('Pinned input SHA256 mismatch: '+str(path))
    a.output_dir.mkdir(parents=True,exist_ok=True);failures=[]
    for case in a.case or ('constant','up-down','invalid-reference','stale-reference'):
        plan=root/'scenarios/e62-v4'/('vbus-'+case+'.csv');scenario=root/'scenarios/e62-v4/handover-drive.json';out=a.output_dir.resolve()/(case+'.json')
        cmd=[sys.executable,str(root/'tests/e62_autonomous_native_motor_probe.py'),'--qemu',str(a.qemu.resolve()),'--elf',str(a.elf.resolve()),'--experimental-candidate-sha256',a.elf_sha256,'--cfg-flash',str(a.cfg_flash.resolve()),'--scenario',str(scenario),'--sim-motor-profile','ecx87-kv147','--sim-native-adc-bemf','--reference-diagnostics','--issue5-bemf-diag','--source-vbus-plan',str(plan),'--differential-sync-start','--wall-timeout-s','600','--artifact',str(out)]
        meta=dict(command=cmd,hashes={str(x):sha(x) for x in (a.qemu,a.elf,a.cfg_flash,plan,scenario)},firmware_source_commit=a.firmware_source_commit,firmware_identity='EXPERIMENTAL_ONLY',p1_qualified=False,hardware_qualified=False)
        out.with_suffix('.command.json').write_text(json.dumps(meta,indent=2)+'\n')
        with out.with_suffix('.stdout.log').open('w') as log:rc=subprocess.run(cmd,cwd=root,stdout=log,stderr=subprocess.STDOUT).returncode
        if rc:failures.append(case);continue
        subprocess.run([sys.executable,'-m','tools.e62_vbus_handover_audit','--log',str(out.with_suffix('.qemu.log')),'--evidence',str(out),'--output',str(out.with_suffix('.handover.json'))],cwd=root,check=True)
    print(json.dumps(dict(probe_failures=failures,p1_qualified=False)));return bool(failures)
if __name__=='__main__':raise SystemExit(main())
