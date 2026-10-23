#!/usr/bin/env python3
"""Pinned original Rel17 WFI role classification is not numeric PC sorting."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from g13b2_native_drive_probe import resolve_original_rel17_wfi_roles


class WfiSourceRoleTests(unittest.TestCase):
    def resolve(self, candidates, locations):
        def fake_addr2line(argv, **kwargs):
            self.assertEqual(argv[0], "arm-none-eabi-addr2line")
            self.assertTrue(kwargs["check"])
            pc = int(argv[-1], 16)
            return subprocess.CompletedProcess(
                argv, 0, locations.get(pc, "??\n??:0\n"), "")
        with patch("g13b2_native_drive_probe.subprocess.run",
                   side_effect=fake_addr2line) as invoke:
            output = resolve_original_rel17_wfi_roles(
                Path("native-test.elf"), candidates)
            self.assertEqual(invoke.call_count, 2)
            return output

    def test_gcc13_running_wfi_lower_address(self):
        self.assertEqual(
            self.resolve((0x679a, 0x6870), {
                0x679a: "am13e_rel17_app_main\n/tmp/ESCape32/src/main.c:1194\n",
                0x6870: "am13e_rel17_app_main\n/tmp/ESCape32/src/main.c:910\n",
            }),
            (0x679a, 0x6870))

    def test_gcc15_arming_wfi_lower_address(self):
        self.assertEqual(
            self.resolve((0x676a, 0x68f8), {
                0x676a: "am13e_rel17_app_main\n/home/build/github/ESCape32/src/main.c:910\n",
                0x68f8: "am13e_rel17_app_main\n/home/build/github/ESCape32/src/main.c:1194\n",
            }),
            (0x68f8, 0x676a))

    def test_unknown_line_fails_closed(self):
        with self.assertRaisesRegex(AssertionError, "Cannot prove"):
            self.resolve((0x100, 0x200), {
                0x100: "am13e_rel17_app_main\n/src/main.c:1194\n",
                0x200: "am13e_rel17_app_main\n/src/main.c:879\n",
            })

    def test_duplicate_role_fails_closed(self):
        with self.assertRaisesRegex(AssertionError, "Duplicated"):
            self.resolve((0x100, 0x200), {
                0x100: "am13e_rel17_app_main\n/src/main.c:910\n",
                0x200: "am13e_rel17_app_main\n/src/main.c:910\n",
            })

    def test_missing_or_duplicated_sites_fail_closed(self):
        for candidates in ((0x100,), (0x100, 0x100), (0x100, 0x200, 0x300)):
            with self.subTest(candidates=candidates):
                with self.assertRaisesRegex(AssertionError, "two distinct"):
                    resolve_original_rel17_wfi_roles(
                        Path("native-test.elf"), candidates)

if __name__ == "__main__":
    unittest.main(verbosity=2)
