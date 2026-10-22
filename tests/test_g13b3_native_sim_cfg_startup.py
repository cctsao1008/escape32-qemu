#!/usr/bin/env python3
"""Never alter production linker and never fabricate Guest cfg writes."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_sim_cfg_startup import derive_sim_cfg_startup, _ORIGINAL


class NativeCfgBootInitTests(unittest.TestCase):
    def fixture(self):
        return (
            "MEMORY { FLASH_APP (rx) : ORIGIN = 0x6000,"
            " LENGTH = 0x7A000; RAM_S (rwx) : ORIGIN = 0x20000000,"
            " LENGTH = 0x18000; FLASH_CFG1 (rx) : ORIGIN = 0x4000,"
            " LENGTH = 0x1000 }\n" + _ORIGINAL +
            "__app_flash_payload_end__ = LOADADDR(.data)+SIZEOF(.data);\n"
            "ASSERT(_cfg_end-_cfg_start<=LENGTH(FLASH_CFG1),"
            " \"config bounds\")\n")

    def test_exact_source_contract_merges_cfg_into_data(self):
        source = self.fixture()
        new = derive_sim_cfg_startup(source)
        self.assertEqual(source.count(".cfg (NOLOAD)"), 1)
        self.assertNotIn(".cfg (NOLOAD)",new)
        self.assertEqual(new.count("KEEP(*(.cfg))"),1)
        self.assertLess(new.index("_cfg_end"),new.index("__data_end__"))
        self.assertIn("SIM_ONLY",new)
        self.assertIn("__data_load__ = LOADADDR(.data)",new)

    def test_source_linker_contract_must_not_change_silently(self):
        for src in (self.fixture().replace("KEEP(*(.cfg))",""),
                    self.fixture().replace(".cfg (NOLOAD)",".cfg"),
                    self.fixture().replace("LOADADDR(.data)+SIZEOF(.data)",
                                           "0xdeadbeef")):
            with self.subTest(src=src[-60:]):
                with self.assertRaises(ValueError):
                    derive_sim_cfg_startup(src)

    def test_multiple_cfg_sections_not_allowed(self):
        with self.assertRaises(ValueError):
            derive_sim_cfg_startup(self.fixture() + _ORIGINAL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
