#!/usr/bin/env python3
"""E62 EXPERIMENT ONLY: two-instruction 3000us clone of pinned Original Rel17.3 ELF.

Byte-exact Control is the published original Guest. Candidate changes
ONLY two Thumb-2 MOVW startup initializations 10000us -> 3000us.
The timeout/reset MOVW #10000 at PC 0x6488 remains byte identical.
This is an experimental *clone*, never called Original Rel17.3, and is
NOT firmware signing, flash safety or physical ESC qualification.

All VAs and opcodes are anchored to verified Original ELF disassembly,
source lines src/main.c:1027 and :1146. Fails closed on any drift.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

PINNED_SHA = "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
# Thumb-2 MOVW: verified independently using clang arm-none-eabi
# with cortex-m33 assembly; GNU objdump source map in CI #40726733552.
SITES = (
    (0x69E4, bytes.fromhex("42f21076"), bytes.fromhex("40f6b836"),
     "src/main.c:1027 ival after sine exit"),
    (0x6A6A, bytes.fromhex("42f21074"), bytes.fromhex("40f6b834"),
     "src/main.c:1146 ival on six-step first start"),
)
PRESERVED_RESET = (0x6488, bytes.fromhex("42f21073"))


def file_sha(b):
    return hashlib.sha256(b).hexdigest()


def load_offset(blob, va, size):
    if blob[:4] != b"\x7fELF" or blob[4:7] != b"\x01\x01\x01":
        raise ValueError("Require little-endian ELF32")
    if struct.unpack_from("<H", blob, 18)[0] != 40:
        raise ValueError("Require ARM ELF, no arbitrary host ELF")
    phoff = struct.unpack_from("<I", blob, 28)[0]
    phentsize = struct.unpack_from("<H", blob, 42)[0]
    n = struct.unpack_from("<H", blob, 44)[0]
    if phentsize != 32 or not 1 <= n <= 32 or phoff + n*32 > len(blob):
        raise ValueError("Invalid ELF32 program headers")
    selected = []
    for j in range(n):
        ptype,off,vaddr,paddr,fsiz,msiz,flags,align = struct.unpack_from(
            "<IIIIIIII", blob, phoff+j*32)
        if ptype==1 and flags&1 and vaddr <= va and va+size <= vaddr+fsiz:
            if off+fsiz>len(blob):
                raise ValueError("ELF executable segment beyond source bytes")
            selected.append(off+va-vaddr)
    if len(selected) != 1:
        raise ValueError("Ambiguous or unavailable executable ELF VA "+hex(va))
    return selected[0]


def patch_ival(original):
    if file_sha(original) != PINNED_SHA:
        raise ValueError("Original Rel17.3 pinned SHA mismatch")
    candidate = bytearray(original)
    proof = []
    all_diffs = set()
    for va,old,new,reason in SITES:
        off = load_offset(original, va, len(old))
        if original[off:off+4] != old:
            raise ValueError(f"Original startup opcode drift at {va:#x}")
        candidate[off:off+4] = new
        diff = [off+i for i in range(4) if old[i]!=new[i]]
        all_diffs.update(diff)
        proof.append(dict(guest_virtual_address=hex(va),
                          elf_file_offset=off,
                          before_thumb2_movw=old.hex(),
                          after_thumb2_movw=new.hex(),
                          source=reason,
                          changed_byte_offsets=diff))
    reset_va,reset_old = PRESERVED_RESET
    reset_offset = load_offset(original,reset_va,len(reset_old))
    if original[reset_offset:reset_offset+4] != reset_old or (
            candidate[reset_offset:reset_offset+4]!=reset_old):
        raise ValueError("Original timeout/fault reset policy changed")
    observed = {i for i,(a,b) in enumerate(zip(original,candidate)) if a!=b}
    if observed!=all_diffs or len(original)!=len(candidate):
        raise AssertionError("Unexpected ELF byte changes")
    return bytes(candidate), dict(
        mode="EXPERIMENTAL_CLONE_NOT_ORIGINAL",
        original_sha256=file_sha(original),
        candidate_sha256=file_sha(candidate),
        changed_bytes=len(observed),
        changed_offsets=sorted(observed),
        changed_instructions=len(SITES),
        startup_filter_before_us=10000,
        startup_filter_after_us=3000,
        unchanged_timeout_reset=True,
        unchanged_p0_p1_acceptance=True,
        no_board_gate_oc_or_guest_memory_modification=True,
        no_runtime_host_guest_writes=True,
        candidate_hardware_qualified=False,
        motor_p1_qualified=False,
        source_sites=proof,
    )


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--elf",type=Path,required=True)
    p.add_argument("--output-elf",type=Path,required=True)
    p.add_argument("--proof-json",type=Path,required=True)
    args=p.parse_args()
    if args.elf.resolve()==args.output_elf.resolve():
        p.error("Refusing to overwrite immutable Original Rel17.3 ELF")
    original=args.elf.read_bytes()
    clone,proof=patch_ival(original)
    args.output_elf.parent.mkdir(parents=True,exist_ok=True)
    args.output_elf.write_bytes(clone)
    if file_sha(args.output_elf.read_bytes())!=proof["candidate_sha256"]:
        raise IOError("Candidate ELF write integrity failed")
    args.proof_json.write_text(json.dumps(proof,sort_keys=True,indent=2)+"\n")
    print("E62_EXPERIMENTAL_PINNED_ELF_TWO_MOVW_PATCH "+
          json.dumps(proof,sort_keys=True))


if __name__=="__main__":
    main()
