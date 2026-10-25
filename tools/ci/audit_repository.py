#!/usr/bin/env python3
"""Fail-closed repository organization audit; never alters the Guest or QEMU.

Validates known public entrypoints, current-document internal backlinks and
bit-identical historical material. Prints tracked file counts by directory.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
ARCHIVE_SHA={
    'docs/history/README-development-log.md':
        '976cae4cc2e06b04c22d060bd25429ba2f1cb9f9',
    'docs/history/e62-autonomous-functional-sitl.md':
        '23a7d45a3b358a528ead153e0f881d80f8f27df0',
    'docs/history/e62-g13b7-autonomous-stage-regression.md':
        'b5e1df0e533a7a4e8bd5f31d523c27f736abb46d',
    'docs/history/e62-g13b7-1-correctness-review.md':
        'e2b0bf747ad568afc4292f952617fb33a88660f8',
}
REQUIRED=(
    'README.md',
    'docs/README.md',
    'docs/current/architecture.md',
    'docs/current/functional-sitl.md',
    'docs/current/test-matrix.md',
    'tests/functional_dshot_sitl.py',
    'tests/g13b4_functional_dshot_sitl.py',
    'tests/g13b2_native_drive_probe.py',
    'tools/native_arming.py',
    'tools/sitl_autonomous_transport.py',
    'tools/sitl_autonomous_evidence.py',
    'tools/sitl_stage_oracle.py',
    'tools/autonomous_sitl_host.py',
    'baseline/e62-g13b3/firmware/AM13E-rev17.3.elf',
    'baseline/e62-g13b3/SHA256SUMS',
    '.github/workflows/e62-pinned-regression.yml',
    '.github/workflows/g13b7-correctness.yml',
)

def git_blob_sha(payload):
    return hashlib.sha1(('blob %d\0' % len(payload)).encode() + payload).hexdigest()

def audit():
    tracked=subprocess.check_output(
        ['git','-C',str(ROOT),'ls-files','-z']).split(b'\0')
    paths={p.decode() for p in tracked if p}
    problems=[]
    for path in REQUIRED:
        if path not in paths or not (ROOT/path).is_file():
            problems.append('required_path_missing:'+path)
    for path,expect in ARCHIVE_SHA.items():
        file=ROOT/path
        if not file.is_file() or git_blob_sha(file.read_bytes()) != expect:
            problems.append('archival_git_blob_modified:'+path)
    current=['README.md','docs/README.md',
             'docs/current/architecture.md',
             'docs/current/functional-sitl.md',
             'docs/current/test-matrix.md']
    link_count=0
    for path in current:
        file=ROOT/path
        if not file.exists(): continue
        for dest in re.findall(r'\]\(([^)]+)\)',file.read_text()):
            dest=dest.split('#',1)[0].strip()
            if not dest or '://' in dest or dest.startswith('#'):
                continue
            link_count+=1
            resolved=(file.parent/dest).resolve()
            if not resolved.is_relative_to(ROOT.resolve()) or not resolved.exists():
                problems.append(f'dead_internal_markdown_link:{path}:{dest}')
    counts={}
    for p in paths:
        prefix=p.split('/',1)[0] if '/' in p else '<root>'
        counts[prefix]=counts.get(prefix,0)+1
    result={'status':'PASS' if not problems else 'FAIL',
            'tracked_files':len(paths),
            'tracked_by_root':dict(sorted(counts.items())),
            'locked_historical_git_blobs':len(ARCHIVE_SHA),
            'checked_current_markdown_links':link_count,
            'problems':problems,
            'scope':'REPO_STRUCTURE_NOT_NATIVE_GUEST_VALIDATION'}
    print('E62_REPOSITORY_AUDIT '+json.dumps(result,sort_keys=True),flush=True)
    return not problems

if __name__=='__main__':
    sys.exit(0 if audit() else 1)
