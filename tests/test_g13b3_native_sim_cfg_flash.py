#!/usr/bin/env python3
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_sim_cfg_flash import (
    extract_cfgdata,factory_image,verify_source_cfg)


def make_cfg():
    x=bytearray(344)
    struct.pack_into("<H",x,0,0x32ea)
    x[2],x[3]=17,3
    x[20]=x[21]=1
    for index,value in ((27,24),(28,48),(30,100),(31,15),(33,100)):
        x[index]=value
    return bytes(x)


def make_elf(cfg):
    elf=bytearray(0x700)
    ident=b"\x7fELF"+bytes((1,1,1))+bytes(9)
    struct.pack_into("<16sHHIIIIIHHHHHH",elf,0,
        ident,2,40,1,0x6001,52,0x600,0,52,32,1,40,4,0)
    struct.pack_into("<IIIIIIII",elf,52,1,0x100,0x7000,0x7000,
                     len(cfg),len(cfg),4,4)
    elf[0x100:0x100+len(cfg)]=cfg
    strings=b"\0cfgdata\0"
    elf[0x550:0x550+len(strings)]=strings
    struct.pack_into("<IIIBBH",elf,0x510,1,0x7000,len(cfg),0x11,0,1)
    # sections: 0 null; 1 rodata; 2 symtab; 3 strtab
    struct.pack_into("<IIIIIIIIII",elf,0x600+40,
        0,1,2,0x7000,0x100,len(cfg),0,0,4,0)
    struct.pack_into("<IIIIIIIIII",elf,0x600+80,
        0,2,0,0,0x500,32,3,0,4,16)
    struct.pack_into("<IIIIIIIIII",elf,0x600+120,
        0,3,0,0,0x550,len(strings),0,0,1,0)
    return bytes(elf)


class OriginalCfgFlash(unittest.TestCase):
    def test_original_source_exact_flash_provision(self):
        cfg=make_cfg()
        payload,meta=factory_image(make_elf(cfg))
        self.assertEqual(payload[:len(cfg)],cfg)
        self.assertEqual(payload[len(cfg):],b"\xff"*4)
        self.assertEqual(meta["flash_base"],"0x00004000")
        self.assertEqual(meta["duty_rate_tenth_pct_per_ms"],100)
    def test_one_byte_cfg_rate_mismatch_fails_closed(self):
        cfg=bytearray(make_cfg())
        cfg[33]=30
        with self.assertRaisesRegex(ValueError,"differs"):
            verify_source_cfg(bytes(cfg))
        with self.assertRaises(ValueError):
            extract_cfgdata(make_elf(bytes(cfg)))
    def test_missing_symbol_or_truncated_elf_refused(self):
        with self.assertRaises(ValueError):
            extract_cfgdata(b"ELF")
        bad=bytearray(make_elf(make_cfg()))
        bad[0x551:0x558]=b"wrongxx"
        with self.assertRaisesRegex(ValueError,"one exact"):
            extract_cfgdata(bytes(bad))
    def test_non_source_cfg_id_cannot_look_like_trial(self):
        bad=bytearray(make_cfg())
        bad[0]=0
        with self.assertRaises(ValueError):
            factory_image(make_elf(bytes(bad)))

if __name__=="__main__":
    unittest.main(verbosity=2)
