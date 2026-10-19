#!/usr/bin/env python3
"""Read the ORIGINAL supplied ARM ELF reset vector (never patch guest bytes).

Rel17.3 is a firmware target name, not a fixed instruction address: the
AM13E HAL can change while retaining the unmodified Rel17 control algorithm.
Require the vector to come from a real file-backed PT_LOAD at APP_BASE.
"""
import struct
from pathlib import Path

APP_BASE = 0x00006000
EXPECTED_SP = 0x20018000


def app_vector_from_elf(path):
    blob = Path(path).read_bytes()
    if len(blob) < 52 or blob[:6] != b"\x7fELF\x01\x01":
        raise ValueError("Expected a little-endian ELF32 file")
    fields = struct.unpack_from("<16sHHIIIIIHHHHHH", blob)
    e_type, machine, e_entry = fields[1], fields[2], fields[4]
    phoff, ehsize, phentsize, phnum = fields[5], fields[8], fields[9], fields[10]
    if e_type != 2 or machine != 40 or ehsize != 52 or phentsize != 32:
        raise ValueError("Expected an ARM ELF32 executable")
    if not phnum or phoff + phnum * phentsize > len(blob):
        raise ValueError("Invalid ELF program header table")
    matches = []
    for index in range(phnum):
        offset = phoff + index * phentsize
        p_type, fileoff, _vaddr, paddr, filesz, _memsz, _flags, _align = (
            struct.unpack_from("<IIIIIIII", blob, offset))
        if p_type != 1 or paddr > APP_BASE or APP_BASE + 8 > paddr + filesz:
            continue
        start = fileoff + (APP_BASE - paddr)
        if start + 8 > len(blob):
            raise ValueError("ELF LOAD extends beyond file")
        matches.append(struct.unpack_from("<II", blob, start))
    if len(matches) != 1:
        raise ValueError("AM13E application vector must occur in exactly one PT_LOAD")
    sp, reset = matches[0]
    if (sp != EXPECTED_SP or not (reset & 1) or
            not APP_BASE <= (reset & ~1) < 0x80000 or e_entry != reset):
        raise ValueError(
            f"Unexpected AM13E image: SP=0x{sp:08x}, RESET=0x{reset:08x}, "
            f"ELF_ENTRY=0x{e_entry:08x}")
    return sp, reset
