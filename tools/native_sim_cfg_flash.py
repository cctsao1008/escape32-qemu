#!/usr/bin/env python3
"""G13B3N SIM_ONLY native Rel17 Cfg FLASH 0x4000 pre-boot image.

Extract EXACT original Cfg cfgdata bytes from the genuine original ARM ELF.
Never synthesize user settings, patch Firmware Cfg SRAM or bypass Rel17
main.c:792 memcpy(_cfg_start,_cfg,_cfg_end-_cfg_start). QEMU generic
loader programs only Flash 0x4000 BEFORE CPU reset; this is a factory
provisioning simulation, not an E62 manufacturing process.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

FLASH_CFG=0x4000
APP_START=0x6000
APP_END=0x80000
ABI_EXPECTED={
    "freq_min_khz":(27,24),
    "freq_max_khz":(28,48),
    "duty_max_pct":(30,100),
    "duty_spup_pct":(31,15),
    "duty_rate_tenth_pct_per_ms":(33,100)
}


def verify_source_cfg(cfg:bytes)->dict:
    if not 256 <= len(cfg) <= 1024 or len(cfg)>4096:
        raise ValueError("Original source Cfg symbol size out of bounds")
    if struct.unpack_from("<H",cfg,0)[0]!=0x32ea or cfg[2:4]!=bytes((17,3)):
        raise ValueError("Not original ESCape32 Rel17.3 Cfg data")
    mismatch={key:dict(expected=expected,actual=cfg[pos])
              for key,(pos,expected) in ABI_EXPECTED.items()
              if cfg[pos]!=expected}
    if mismatch:
        raise ValueError("Original source Cfg differs from explicit G13B3L "
                         "SIM_ONLY trial: "+json.dumps(mismatch,sort_keys=True))
    if cfg[20]!=1 or cfg[21]!=1:
        raise ValueError("Original ARM/DAMP policy not source-default 1")
    return {
        "cfg_id":"0x32ea","rel":"17.3","source_bytes":len(cfg),
        "sha256":hashlib.sha256(cfg).hexdigest(),
        **{k:v for k,(_,v) in ABI_EXPECTED.items()}
    }


def extract_cfgdata(elf:bytes)->bytes:
    if len(elf)<52 or elf[:6]!=b"\x7fELF\x01\x01":
        raise ValueError("Expected genuine little-endian ELF32")
    hdr=struct.unpack_from("<16sHHIIIIIHHHHHH",elf,0)
    e_type,e_machine,e_phoff,e_shoff=hdr[1],hdr[2],hdr[5],hdr[6]
    ehsize,phentsize,phnum,shentsize,shnum=hdr[8:13]
    if (e_type!=2 or e_machine!=40 or ehsize!=52 or phentsize!=32 or
        shentsize!=40 or not phnum or not shnum or
        e_phoff+32*phnum>len(elf) or e_shoff+40*shnum>len(elf)):
        raise ValueError("Invalid original ARM ELF header or tables")
    sections=[
        struct.unpack_from("<IIIIIIIIII",elf,e_shoff+40*i)
        for i in range(shnum)]
    matches=[]
    for sec in sections:
        if sec[1]!=2:
            continue
        offset,size,link,entsize=sec[4],sec[5],sec[6],sec[9]
        if (link>=shnum or entsize!=16 or size%16 or
            offset+size>len(elf)):
            raise ValueError("Invalid original .symtab")
        strings=sections[link]
        if strings[1]!=3 or strings[4]+strings[5]>len(elf):
            raise ValueError("Invalid original .strtab")
        names=elf[strings[4]:strings[4]+strings[5]]
        for pos in range(offset,offset+size,16):
            name,val,length,info,other,section=struct.unpack_from(
                "<IIIBBH",elf,pos)
            if name>=len(names):
                raise ValueError("ELF symbol name out of string table")
            end=names.find(b"\0",name)
            if end<0:
                raise ValueError("ELF symbol name unterminated")
            if names[name:end]!=b"cfgdata":
                continue
            if (info&15)!=1 or not APP_START<=val<APP_END or
                not 256<=length<=1024 or val+length>APP_END or
                section>=shnum):
                raise ValueError("Invalid source cfgdata object symbol")
            matches.append((val,length))
    if len(matches)!=1:
        raise ValueError("Original source cfgdata must be one exact object")
    addr,length=matches[0]
    blobs=[]
    for i in range(phnum):
        ptype,foff,_vaddr,paddr,filesz,_memsz,_flags,_align=(
            struct.unpack_from("<IIIIIIII",elf,e_phoff+32*i))
        if (ptype==1 and paddr<=addr and
            addr+length<=paddr+filesz and foff+filesz<=len(elf)):
            begin=foff+addr-paddr
            blobs.append(elf[begin:begin+length])
    if len(blobs)!=1:
        raise ValueError("Original cfgdata not uniquely present in file-backed FLASH APP")
    verify_source_cfg(blobs[0])
    return blobs[0]


def factory_image(elf:bytes)->tuple[bytes,dict]:
    cfg=extract_cfgdata(elf)
    # Preserve full aligned original Cfg sector header; only harmless
    # erased-Flash padding is added. Never invent any config fields.
    pad=(-len(cfg))%8
    image=cfg+b"\xff"*pad
    meta=verify_source_cfg(cfg)
    meta.update(
        flash_base=f"0x{FLASH_CFG:08x}",
        padded_bytes=len(image),padded_erased_bytes=pad,
        provenance="GENUINE_ELF_SOURCE_CFGDATA_NOT_GUEST_SRAM",
        mode="SIM_ONLY_PRE_CPU_FLASH_PROVISIONING")
    return image,meta


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--sim-only-opt-in",action="store_true",required=True)
    p.add_argument("--elf",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if "g13b3" not in a.output.name.lower() or a.output.suffix!=".bin":
        p.error("Output must be dedicated G13B3 SIM_ONLY Flash image")
    if not a.elf.is_file():
        p.error("Missing genuine original ELF")
    image,meta=factory_image(a.elf.read_bytes())
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_bytes(image)
    print("PASS_G13B3N_SOURCE_CFGDATA_FACTORY_FLASH_IMAGE "+
          json.dumps(meta,sort_keys=True),flush=True)


if __name__=="__main__":
    main()
