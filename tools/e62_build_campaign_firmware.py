"""Build a clean pinned experimental AM13E source with CFG-safe ELF page layout."""
import argparse,hashlib,json,shutil,subprocess
from pathlib import Path
SDK_PIN='b872469ceef18de5e39a1d3acb0821ec158b44c7'
def git(path,*args):return subprocess.check_output(['git','-C',str(path),*args],text=True).strip()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source','sdk','qemu-root','build-dir','metadata'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--source-commit',required=True);p.add_argument('--profile',required=True);a=p.parse_args();src=a.source.resolve();profile=src/'mcu/_support/AM13E/cmake/test_profiles'/a.profile
    if git(src,'rev-parse','HEAD')!=a.source_commit or git(src,'status','--porcelain'):raise SystemExit('Firmware source must be clean at the explicit pinned commit')
    if git(a.sdk,'rev-parse','HEAD')!=SDK_PIN or git(a.sdk,'diff','HEAD','--','source'):raise SystemExit('Official SDK source pin/content changed')
    if not profile.is_file() or src not in profile.resolve().parents:raise SystemExit('Unknown source-owned profile')
    compiler=Path(shutil.which('arm-none-eabi-gcc') or '')
    if not compiler.is_file():raise SystemExit('Activate the existing toolchain first')
    cmd=['cmake','-S',str(src),'-B',str(a.build_dir.resolve()),'-DESCAPE32_BUILD_AM13E=ON','-DAM13E_MOTOR_RUNTIME_ENABLED=ON','-DAM13E_SDK_ROOT='+str(a.sdk.resolve()),'-DE62_QEMU_ROOT='+str(a.qemu_root.resolve()),'-DCMAKE_EXE_LINKER_FLAGS=-Wl,-z,max-page-size=0x1000','-DG13B2_SIM_ONLY_OPT_IN=ON','-DG13B2_SIM_ONLY_IDEAL_BEMF_REFERENCE=OFF','-DAM13E_BOARD_BOARD_PROFILE_FILE='+str(profile)]
    build=['cmake','--build',str(a.build_dir.resolve()),'--target','AM13E-rev17.3.elf','-j2']
    meta=dict(firmware_source_commit=a.source_commit,sdk_commit=SDK_PIN,profile=str(profile),configure_command=cmd,build_command=build,compiler=str(compiler),compiler_sha256=hashlib.sha256(compiler.read_bytes()).hexdigest(),compiler_version=subprocess.check_output([str(compiler),'--version'],text=True).splitlines()[0],identity='EXPERIMENTAL_NOT_ORIGINAL_OR_PRODUCTION_ROOT_FIXES')
    a.metadata.parent.mkdir(parents=True,exist_ok=True)
    for phase,argv in (('configure',cmd),('build',build)):
        logfile=a.metadata.with_suffix('.'+phase+'.log')
        with logfile.open('w') as log:rc=subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT).returncode
        meta[phase+'_rc']=rc;meta[phase+'_log']=str(logfile);a.metadata.write_text(json.dumps(meta,indent=2)+'\n')
        if rc:return rc
    elf=a.build_dir/'AM13E-rev17.3.elf';meta.update(elf_path=str(elf.resolve()),elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest());a.metadata.write_text(json.dumps(meta,indent=2)+'\n');print(meta['elf_sha256']);return 0
if __name__=='__main__':raise SystemExit(main())
