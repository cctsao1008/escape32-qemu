#!/usr/bin/env python3
"""Independent integrity-only audit of immutable E62 G13B3 binary archive.

A valid file checksum proves saved bytes match the saved manifest; it
DOES NOT prove the archived QEMU was built from *current* Machine source.
The strict historical source-pair verifier remains unchanged and red
after source drift. This checker NEVER claims rotor stability.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
BUNDLE='baseline/e62-g13b3'
FILES=('firmware/AM13E-rev17.3.elf',
       'qemu/linux-x86_64/qemu-system-arm',
       'qemu/linux-x86_64/libfdt.so.1')
EXPECTED_ELF='05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()

def audit(root=ROOT, *, expected_elf=EXPECTED_ELF):
    base=Path(root)/BUNDLE
    problems=[]
    try:
        meta=json.loads((base/'manifest.json').read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:
        return {'status':'FAIL_ARCHIVE_INTEGRITY','issues':['manifest_missing_or_invalid'],
                'scope':'HISTORICAL_BYTES_ONLY_NOT_SOURCE_OR_ROTOR_QUALIFICATION'}

    if (meta.get('schema')!='e62-g13b3-paired-binary-baseline.v1' or
        meta.get('id')!='E62-G13B3-SIM_ONLY-UBUNTU24-X86_64-v1'):
        problems.append('archive_manifest_identity_mismatch')
    specs=meta.get('files')
    if not isinstance(specs,dict) or set(specs)!=set(FILES):
        problems.append('archive_files_manifest_unexpected')
        specs={}
    verified={}
    for rel in FILES:
        path=base/rel
        spec=specs.get(rel) or {}
        if not path.is_file() or path.is_symlink():
            problems.append('archive_file_missing_or_symlink:'+rel)
            continue
        real_size=path.stat().st_size
        expected_size=spec.get('size_bytes')
        real_sha=digest(path)
        if real_size!=expected_size or real_sha!=spec.get('sha256'):
            problems.append('archive_binary_checksum_mismatch:'+rel)
        verified[rel]=real_sha
    if verified.get(FILES[0])!=expected_elf:
        problems.append('original_escap32_elf_sha_mismatch')
    try:
        ledger=(base/'SHA256SUMS').read_text(encoding='utf-8')
        expected=''.join(f'{verified.get(p, "MISSING")}  {p}\n' for p in FILES)
        if ledger!=expected:
            problems.append('archive_SHA256SUMS_ledger_mismatch')
    except OSError:
        problems.append('archive_SHA256SUMS_missing')

    source=(meta.get('qemu') or {}).get('source_tree_sha256') or {}
    if not isinstance(source,dict) or not source:
        problems.append('archive_missing_source_provenance_hashes')
        source={}
    drift=[]
    for rel,recorded in source.items():
        file=Path(root)/rel
        if not file.is_file() or digest(file)!=recorded:
            drift.append(rel)
    summary={
        'status':('PASS_HISTORICAL_BYTES_INTEGRITY_ONLY'
                  if not problems else 'FAIL_ARCHIVE_INTEGRITY'),
        'issues':problems,
        'checked_binary_files':len(verified),
        'current_source_drift':bool(drift),
        'current_source_drift_files':drift,
        'current_source_pair_qualified':len(drift)==0 and not problems,
        'original_g13b3m_rotor_stability':'KNOWN_FAIL_UNWAIVED',
        'scope':'ARCHIVED_BINARIES_AS_SAVED_NOT_CURRENT_BUILD_PROVENANCE_OR_ROTOR',
    }
    return summary

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--repo',type=Path,default=ROOT)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    result=audit(args.repo)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',
                               encoding='utf-8')
    print('E62_G13B3_HISTORICAL_ARCHIVE_INTEGRITY '+
          json.dumps(result,sort_keys=True),flush=True)
    return 1 if result['issues'] else 0

if __name__=='__main__':sys.exit(main())
