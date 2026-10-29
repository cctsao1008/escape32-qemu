#!/usr/bin/env python3
"""Fail-closed check: only one DAC immediate byte differs in loaded ARM ELF.

This is an exact-source, exact-toolchain, SIM_ONLY experimental fixture.
The binary proof is intentionally pinned and rejects all relocated/changed
linker layouts, build-path strings and unanticipated control-instruction
changes. It does not establish silicon calibration or enable flashing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

BASELINE_SHA = "5b90b200429333cef82b982b7a7f845f31fb885c7ea63fc7e783c75232fac8d1"
ALLOWED_PHYSICAL_ADDRESS = 0xC190
EXPECTED_CHANGED_BYTE = {16: 0x01, -16: 0xFE}


def read_elf(path):
    data = path.read_bytes()
    if data[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("Only little-endian ARM ELF32 allowed")
    if struct.unpack_from("<H",data,18)[0]!=40:
        raise ValueError("Not ARM ELF")
    entry = struct.unpack_from("<I",data,24)[0]
    off=struct.unpack_from("<I",data,28)[0]
    entsz=struct.unpack_from("<H",data,42)[0]
    num=struct.unpack_from("<H",data,44)[0]
    if entsz != 32 or num>32 or num<1 or off+entsz*num>len(data):
        raise ValueError("Untrusted / invalid program headers")
    loads=[]
    for i in range(num):
        kind,po,va,pa,n,mem,flags,align=struct.unpack_from(
            "<IIIIIIII",data,off+i*entsz)
        if kind!=1:
            continue
        if n>mem or po+n>len(data):
            raise ValueError("Invalid loadable segment")
        loads.append({"vaddr":va,"paddr":pa,"filesz":n,
                      "memsz":mem,"flags":flags,"align":align,
                      "data":data[po:po+n]})
    if not loads:
        raise ValueError("No loadable ARM segment")
    return data,entry,loads


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--control",type=Path,required=True)
    p.add_argument("--matched",type=Path,required=True)
    p.add_argument("--offset",type=int,choices=(-16,16),required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    raw_c,entry_c,ctrl=read_elf(a.control)
    raw_m,entry_m,matched=read_elf(a.matched)
    source_hash=hashlib.sha256(raw_c).hexdigest()
    if source_hash!=BASELINE_SHA:
        p.error("Control is NOT the exact previously validated source-built filtered ELF")
    if entry_c!=entry_m or len(ctrl)!=len(matched):
        p.error("Different ARM entry point or loadable segment count")
    diffs=[]
    for x,y in zip(ctrl,matched):
        keys=("vaddr","paddr","filesz","memsz","flags","align")
        if any(x[k]!=y[k] for k in keys):
            p.error("Different loadable segment memory or layout")
        for idx,(u,v) in enumerate(zip(x["data"],y["data"])):
            if u!=v:
                diffs.append((x["paddr"]+idx,u,v))
    expected=[(ALLOWED_PHYSICAL_ADDRESS,0,EXPECTED_CHANGED_BYTE[a.offset])]
    if diffs!=expected:
        p.error("SIM_ONLY DAC variant modified unexpected LOAD bytes: "+
                str(diffs[:16])+"; count="+str(len(diffs)))
    proof={
        "schema":"e62.sim-only.bemf-dac-reference-elf-loaded-diff.v1",
        "classification":"EXACT_SINGLE_LOADED_DAC_IMMEDIATE_ONLY",
        "control_elf_sha256":source_hash,
        "matched_elf_sha256":hashlib.sha256(raw_m).hexdigest(),
        "control_not_original_p1":True,"hardware_qualified":False,
        "source_model_offset_code":a.offset,
        "control_dac_code":2048,
        "matched_dac_code":2048+a.offset,
        "changed_physical_address":hex(ALLOWED_PHYSICAL_ADDRESS),
        "old_code_byte":hex(expected[0][1]),
        "new_code_byte":hex(expected[0][2]),
        "unchanged_loadable_segments_except_one_byte":True,
        "entrypoint_unchanged":True,
        "not_board_calibration":True,
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(proof,sort_keys=True,indent=2)+"\n")
    print("PASS_E62_MODEL_BEMF_DAC_SINGLE_BYTE_DIFF "+json.dumps(proof,sort_keys=True))


if __name__=="__main__":
    main()
