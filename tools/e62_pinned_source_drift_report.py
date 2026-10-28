#!/usr/bin/env python3
"""Read-only historical G13B3 binary/source fingerprint discrepancy audit.

This tool is diagnostic only: never relabels the archived binary/source pair
qualified, edits manifest, rebuilds binaries, or disables the original strict
verifier. SOURCE_FILES comes verbatim from the existing pinned baseline tool.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.e62_pinned_baseline import SOURCE_FILES

def diff(expected,actual):
    names=set(expected)|set(actual)
    out=[]
    for name in sorted(names):
        if name not in expected:
            status="UNPINNED_NEW_FILE"
        elif name not in actual:
            status="SOURCE_FILE_MISSING"
        elif expected[name]!=actual[name]:
            status="SOURCE_SHA256_DRIFT"
        else:
            status="MATCH"
        out.append({"file":name,"status":status,
                    "pinned_sha256":expected.get(name),
                    "current_sha256":actual.get(name)})
    return out

def calculate(root):
    manifest_path=root/"baseline/e62-g13b3/manifest.json"
    manifest_bytes=manifest_path.read_bytes()
    metadata=json.loads(manifest_bytes)
    pinned=metadata["qemu"]["source_tree_sha256"]
    if not isinstance(pinned,dict) or set(pinned)!=set(SOURCE_FILES):
        raise ValueError("historical pinned source-file set invalid")
    actual={}
    for name in SOURCE_FILES:
        path=root/name
        if not path.is_file() or path.is_symlink():
            continue
        actual[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    records=diff(pinned,actual)
    mismatches=[x for x in records if x["status"]!="MATCH"]
    return {
        "schema":"e62-g13b3-readonly-source-drift.v1",
        "scope":"HISTORICAL_BINARY_SOURCE_FINGERPRINT_DIAGNOSTIC_ONLY",
        "status":("PINNED_SOURCE_IDENTITY_MATCHES" if not mismatches else
                  "HISTORICAL_SOURCE_DRIFT_CONFIRMED_NOT_WAIVED"),
        "archived_manifest_sha256":hashlib.sha256(manifest_bytes).hexdigest(),
        "source_file_count":len(SOURCE_FILES),
        "match_count":len(records)-len(mismatches),
        "drift_count":len(mismatches),
        "source_records":records,
        "strict_original_verifier_passing":len(mismatches)==0,
        "archived_binary_pair_republished":False,
        "archive_manifest_modified":False,
        "binary_byte_integrity_checked_by_this_tool":False,
        "interpretation":"The original tools/e62_pinned_baseline.py verify "
          "must remain strict. A source-drift diagnostic SUCCESS does not "
          "mean archived QEMU and current machine source are identical."
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    result=calculate(ROOT)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("E62_HISTORICAL_SOURCE_DIAGNOSTIC "+json.dumps({
        "status":result["status"],"drift_count":result["drift_count"],
        "nonmatching_files":[r["file"] for r in result["source_records"]
            if r["status"]!="MATCH"]},sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
