"""Initialize the native fixture paused; malformed plans must fail before Guest execution."""
import argparse,hashlib,json,subprocess,tempfile
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('qemu','elf','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();rows=[]
    cases={'valid_constant':'0,24000,0','valid_changes':'0,24000,0\n20,23000,0\n24,24500,0','wrong_initial':'0,23000,0','missing_initial':'1,24000,0','duplicate_frame':'0,24000,0\n0,23000,0','outside_voltage':'0,24000,0\n20,27000,0','unknown_sensor':'0,24000,3','negative_frame':'-1,24000,0','trailing_data':'0,24000,0junk','too_many':'\n'.join(f'{i},24000,0' for i in range(17)),'wrong_version':'WRONG\n0,24000,0'}
    with tempfile.TemporaryDirectory(prefix='e62-vbus-plan-') as tmp:
        for name,body in cases.items():
            plan=Path(tmp)/'plan.csv';plan.write_text(('' if name=='wrong_version' else 'E62_SIM_VBUS_V1\n')+body+'\n')
            cmd=[str(a.qemu.resolve()),'-M','am13e23019,esc-sim=on,esc-sim-native-motor=on,esc-sim-native-adc-bemf=on,esc-sim-vbus-plan='+str(plan),'-kernel',str(a.elf.resolve()),'-S','-display','none','-serial','none','-monitor','none']
            child=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            initialized=False
            try:out,err=child.communicate(timeout=0.5)
            except subprocess.TimeoutExpired:
                initialized=True;child.terminate();out,err=child.communicate(timeout=5)
            expected_valid=name.startswith('valid_')
            ok=initialized if expected_valid else child.returncode!=0 and b'E62_VBUS_PLAN' in err
            rows.append(dict(name=name,plan=plan.read_text(),command=cmd,expected_valid=expected_valid,initialized_paused=initialized,exit_code=child.returncode,stderr=err.decode(errors='replace'),passed=ok))
    result=dict(schema='e62.vbus-plan-initialization.v1',qemu_sha256=hashlib.sha256(a.qemu.read_bytes()).hexdigest(),elf_sha256=hashlib.sha256(a.elf.read_bytes()).hexdigest(),guest_executed=False,cases=rows,passed=all(r['passed'] for r in rows),hardware_qualified=False)
    a.output.write_text(json.dumps(result,indent=2)+'\n');print('PASS' if result['passed'] else 'FAIL');return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
