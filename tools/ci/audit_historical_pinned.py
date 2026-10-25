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
# Independent constants captured at the ORIGINAL pinned G13B3 release.
# A replacement binary + rewritten manifest must still fail.
PUBLISHED_BINARIES={
    'firmware/AM13E-rev17.3.elf':
        ('05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0',1727132),
    'qemu/linux-x86_64/qemu-system-arm':
        ('5c56a11ff662ccdb7e6280f78f77c6787707cef530b535958a587713d477719b',79883640),
    'qemu/linux-x86_64/libfdt.so.1':
        ('66c111808e61c7f6be6715b4b03d0fe75beb5bc5b3a8809608d58d99a6bc9828',39064)
}
ORIGINAL_QEMU_UPSTREAM='44f28df24767cf9dca1ddc9b23157737c4cbb645'
ORIGINAL_GUEST_SOURCE='b0204670515d2de0b2480b52273038f1ee13d30a'
ORIGINAL_TI_SDK='b872469ceef18de5e39a1d3acb0821ec158b44c7'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()

def audit(root=ROOT, *, expected_archive=PUBLISHED_BINARIES):
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
    qemu=meta.get('qemu') or {}
    guest=meta.get('guest') or {}
    provenance=meta.get('provenance') or {}
    if (qemu.get('upstream_revision')!=ORIGINAL_QEMU_UPSTREAM or
        guest.get('source_revision')!=ORIGINAL_GUEST_SOURCE or
        guest.get('ti_sdk_revision')!=ORIGINAL_TI_SDK):
        problems.append('original_archive_release_revision_mismatch')
    if (provenance.get('recorded_g13b3m_90ms_rotor') !=
            'FAIL_ORIGINAL_REVERSE_MOTION'):
        problems.append('archive_rotor_known_failure_provenance_changed')
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
        published_sha,published_size=expected_archive[rel]
        if real_sha!=published_sha or real_size!=published_size:
            problems.append('archived_release_identity_mismatch:'+rel)
        verified[rel]=real_sha
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
        'independent_published_binary_digest_pin':True,
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
