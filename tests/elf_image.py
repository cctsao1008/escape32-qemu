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



def elf_function_address(path, name):
    """Resolve an exact function in the supplied ELF32 symbol table.

    No hardcoded PC offsets: AM13E HAL rebuilds legitimately move TI SDK
    functions.  No objdump dependency, and stripped/ambiguous images fail.
    """
    blob = Path(path).read_bytes()
    if len(blob) < 52 or blob[:6] != b"\x7fELF\x01\x01":
        raise ValueError("Expected a little-endian ELF32 file")
    hdr = struct.unpack_from("<16sHHIIIIIHHHHHH", blob)
    section_off, entry_size, count = hdr[6], hdr[11], hdr[12]
    if not count or entry_size != 40 or section_off + count * entry_size > len(blob):
        raise ValueError("ELF section headers missing or malformed")
    sections = [struct.unpack_from("<IIIIIIIIII", blob, section_off + i * 40)
                for i in range(count)]
    hits = []
    for sh in sections:
        if sh[1] != 2:  # SHT_SYMTAB
            continue
        off, size, link, entsize = sh[4], sh[5], sh[6], sh[9]
        if link >= count or entsize != 16 or size % 16 or off + size > len(blob):
            raise ValueError("Malformed ELF function symbol table")
        string_section = sections[link]
        str_off, str_size = string_section[4], string_section[5]
        if string_section[1] != 3 or str_off + str_size > len(blob):
            raise ValueError("Malformed ELF string table")
        names = blob[str_off:str_off + str_size]
        for pos in range(off, off + size, 16):
            st_name, value, st_size, st_info, _other, _section = (
                struct.unpack_from("<IIIBBH", blob, pos))
            if (st_info & 15) != 2 or st_name >= len(names):
                continue
            end = names.find(b"\0", st_name)
            if end < 0:
                raise ValueError("Unterminated function symbol")
            if names[st_name:end] == name.encode("ascii"):
                hits.append((value & ~1, st_size))
    if len(hits) != 1 or not APP_BASE <= hits[0][0] < 0x80000:
        raise ValueError(f"Missing or ambiguous ELF function symbol: {name}")
    return hits[0]
