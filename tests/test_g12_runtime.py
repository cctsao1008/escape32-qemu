#!/usr/bin/env python3
"""Host-only validation of G12 evidence processing and timebase arithmetic."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from g12_runtime_progress import instruction_budget, int_events, native_wfi_locations


class G12HostEvidence(unittest.TestCase):
    def test_icount_budget_is_only_ns_per_instruction(self):
        self.assertEqual(instruction_budget(2), 15625)
        self.assertEqual(instruction_budget(4), 3906.25)
        self.assertEqual(instruction_budget(10), 61.03515625)
        with self.assertRaises(ValueError):
            instruction_budget(-1)

    def test_only_native_main_disassembled_wfi_is_accepted(self):
        disasm = """
00007000 <am13e_rel17_app_main>:
    7000: bf30       wfi
    7002: bf00       nop
    7004: bf30       wfi
    7100: bf30       wfi
        """
        with patch("g12_runtime_progress.elf_function_address",
                   return_value=(0x7000, 0x100)):
            with patch("g12_runtime_progress.subprocess.run",
                       return_value=SimpleNamespace(stdout=disasm)) as fake:
                self.assertEqual(native_wfi_locations(Path("fake.elf"),
                                                       "arm-none-eabi-objdump"),
                                 (0x7000, 0x7004))
                self.assertIn("--disassemble=am13e_rel17_app_main",
                              fake.call_args.args[0])

    def test_missing_native_wfi_fails_closed(self):
        with patch("g12_runtime_progress.elf_function_address",
                   return_value=(0x7000, 0x100)):
            with patch("g12_runtime_progress.subprocess.run",
                       return_value=SimpleNamespace(stdout="7000: bf00 nop")):
                with self.assertRaisesRegex(AssertionError, "No native Rel17 WFI"):
                    native_wfi_locations(Path("fake.elf"), "objdump")

    def test_only_actual_qemu_exception_log_counts(self):
        content = "\n".join([
            "...taking pending nonsecure exception 15",
            "...taking pending nonsecure exception 14",
            "...taking pending nonsecure exception 15",
            "Exception return: magic PC ffffffb8 previous exception 15",
            "...successful exception return",
            "Exception return: magic PC ffffffb8 previous exception 14",
            "...successful exception return",
            "G11_TRACE_SUMMARY invented exceptions=99",  # not counted
        ])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "int.log"
            path.write_text(content)
            counts, examples = int_events(path)
        self.assertEqual(counts["systick_entry"], 2)
        self.assertEqual(counts["pendsv_entry"], 1)
        self.assertEqual(counts["excret_attempt"], 2)
        self.assertEqual(counts["excret_success"], 2)
        self.assertEqual(counts["excret_integrity_failure"], 0)
        self.assertEqual(len(examples), 3)


if __name__ == "__main__":
    unittest.main()
