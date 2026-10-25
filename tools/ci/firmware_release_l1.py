#!/usr/bin/env python3
"""One-source, one-QEMU-build E62 L1 firmware release functional gate.

Runs independently qualified original-Guest T01/T02, positive/negative
physical DShot CRC, native OC/nFAULT shutdown and modeled WWDT BOOTRST.
G13B3M/clocked rotor/real board are NOT among these L1 acceptance claims.
Every missing, malformed, or unqualified artifact fails closed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.ci.verify_t01 import validate as validate_t01
from tools.ci.verify_t02 import validate as validate_t02
from tools.ci.dshot_crc_qualification import verify_pair
from tools.ci.safety_qualification import verify_all

FAULTS = ("nfault", "oc-u", "oc-v", "oc-w")
MARKERS = {
    "trip": "PASS_G13B2B_THREE_NATIVE_OC_AND_NFAULT_ROUTES_ARMED",
    "wwdt_legacy": "PASS_G5_WWDT",
    "wwdt_bootrst": "PASS_G14_WWDT_OPT_IN_DEVICE_MODEL_ONLY_NOT_GUEST_INPUT_LOSS",
}
RELEASE_STATUS = "PASS_L1_ORIGINAL_GUEST_FUNCTIONAL_SIM_ONLY"
RELEASE_SCOPE = (
    "SAME_ORIGINAL_ELF_QEMU_INSTANCE_BUILD_FUNCTIONAL_SIM_ONLY_NOT_ROTOR"
)

def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda:fh.read(1<<20),b""):
            digest.update(block)
    return digest.hexdigest()

def read_json(root,name,issues):
    path=root/name
    if not path.is_file():
        issues.append("missing:"+name)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        issues.append("invalid_json:"+name)
        return None

def check_evidence(root):
    """Pure deterministic aggregate from complete independently validated artifacts."""
    root=Path(root)
    issues=[]
    gates={}
    t01=read_json(root,"e62-l1-t01.json",issues)
    t02=read_json(root,"e62-l1-t02.json",issues)
    if t01 is not None:
        g=validate_t01(t01)
        gates["T01"]={"status":"PASS" if not g else "FAIL","issues":g}
        issues.extend("T01:"+x for x in g)
    if t02 is not None:
        g=validate_t02(t02)
        gates["T02"]={"status":"PASS" if not g else "FAIL","issues":g}
        issues.extend("T02:"+x for x in g)

    positive=read_json(root,"e62-l1-dshot-valid.json",issues)
    negative=read_json(root,"e62-l1-dshot-badcrc.json",issues)
    if positive is not None and negative is not None:
        g=verify_pair(positive,negative)
        gates["DShot_CRC"]={"status":"PASS" if not g else "FAIL","issues":g}
        issues.extend("DShot_CRC:"+x for x in g)
    faults={}
    for name in FAULTS:
        result=read_json(root,"e62-l1-fault-"+name+".json",issues)
        if result is not None:
            faults[name]=result
    if len(faults)==len(FAULTS):
        outcome=verify_all(faults)
        g=outcome["issues"]
        gates["OC_nFAULT"]={"status":"PASS" if not g else "FAIL",
                           "issues":g,
                           "scope":outcome["scope"]}
        issues.extend("OC_nFAULT:"+x for x in g)

    for key, marker in MARKERS.items():
        path=root/("e62-l1-"+key+".log")
        if not path.is_file():
            issues.append("missing:"+path.name)
            continue
        if marker not in path.read_text(errors="replace"):
            issues.append("missing_marker:"+path.name+":"+marker)
        else:
            gates[key]={"status":"PASS","scope":"MODELED_PERIPHERAL_ONLY"}

    required={"T01","T02","DShot_CRC","OC_nFAULT",*MARKERS}
    if set(gates)!=required:
        issues.append("missing_required_gates:"+
                      ",".join(sorted(required-set(gates))))
    return {
        "status":RELEASE_STATUS if not issues else "FAIL_L1_RELEASE_EVIDENCE",
        "issues":sorted(set(issues)),
        "gates":gates,
        "scope":RELEASE_SCOPE,
        "G13B3M_strict_rotor":"KNOWN_FAIL_SEPARATE_BLOCKING_L2",
        "Guest_coupled_motor_physics":"OPEN_SEPARATE_L2",
        "hardware_qualification":"NOT_QUALIFIED",
        "WWDT_Guest_input_loss_recovery":"OPEN_NOT_PROVEN_BY_DEVICE_TEST",
    }

def _git(root,*args):
    return subprocess.check_output(
        ["git","-C",str(root),*args],text=True).strip()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--evidence-dir",type=Path,required=True)
    p.add_argument("--firmware",type=Path,required=True)
    p.add_argument("--expected-elf-sha256",required=True)
    p.add_argument("--qemu",type=Path,required=True)
    p.add_argument("--release-id",required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()

    root=Path(__file__).resolve().parents[2]
    problems=[]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}",args.release_id):
        problems.append("invalid_release_id")
    firmware=args.firmware.resolve()
    if not firmware.is_relative_to(root) or not firmware.is_file():
        problems.append("release_firmware_not_tracked_local_file")
    else:
        try:
            rel=firmware.relative_to(root).as_posix()
            if rel not in _git(root,"ls-files").splitlines():
                problems.append("release_elf_must_be_git_tracked")
        except (OSError,subprocess.CalledProcessError):
            problems.append("cannot_verify_firmware_git_identity")
    if not re.fullmatch(r"[a-f0-9]{64}",args.expected_elf_sha256):
        problems.append("expected_elf_sha256_invalid")
    actual_elf=sha256(firmware) if firmware.is_file() else None
    if actual_elf!=args.expected_elf_sha256:
        problems.append("ELF_SHA256_MISMATCH")
    qemu=args.qemu.resolve()
    if not qemu.is_file():
        problems.append("custom_qemu_executable_missing")
    measured=check_evidence(args.evidence_dir)
    measured["issues"].extend(problems)
    if problems:
        measured["status"]="FAIL_L1_RELEASE_EVIDENCE"
    measured["release"]={
        "id":args.release_id,"elf_path":str(args.firmware),
        "elf_sha256":actual_elf,
        "expected_elf_sha256":args.expected_elf_sha256,
        "custom_qemu_sha256":sha256(qemu) if qemu.is_file() else None,
        "repo_commit":_git(root,"rev-parse","HEAD"),
        "qemu_submodule_commit":_git(root,"rev-parse","HEAD:qemu"),
        "scenarios_sha256":sha256(root/"scenarios/e62-dshot-v1.json"),
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(measured,indent=2,sort_keys=True)+"\n")
    print("E62_FIRMWARE_RELEASE_L1 "+json.dumps(measured,sort_keys=True),
          flush=True)
    return 0 if measured["status"]==RELEASE_STATUS else 1

if __name__=="__main__":
    sys.exit(main())
