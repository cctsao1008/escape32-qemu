#!/usr/bin/env python3
"""Pinned binary baseline fail-closed contract (no binaries required)."""
import hashlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import e62_pinned_baseline as b


class PinnedBinaryContract(unittest.TestCase):
    def test_original_ci_guest_sha_is_exact_and_not_local_compiler(self):
        self.assertEqual(b.EXPECTED_ELF_SHA256,
          "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0")
        self.assertNotEqual(b.EXPECTED_ELF_SHA256,
          "970f131c59d00459d344b6b8470a66377eff4fa675a5c5a5bc635fdaf78def04")

    def test_expected_machine_and_sdk_source_revision(self):
        self.assertEqual(len(b.QEMU_UPSTREAM_COMMIT),40)
        self.assertEqual(len(b.ESCAPE32_SOURCE_COMMIT),40)
        self.assertEqual(len(b.TI_SDK_COMMIT),40)
        self.assertEqual(set(b.source_hashes()),set(b.SOURCE_FILES))

    def test_checksum_and_elf_architecture_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"bin"
            p.write_bytes(b"hello")
            self.assertEqual(b.digest(p),hashlib.sha256(b"hello").hexdigest())
            with self.assertRaisesRegex(ValueError,"ELF architecture"):
                b.check_binary_header(p,host=True)
            guest=bytearray(64)
            guest[:6]=b"\x7fELF\x01\x01"
            struct.pack_into("<H",guest,18,40)
            p.write_bytes(guest)
            b.check_binary_header(p,host=False)
            with self.assertRaisesRegex(ValueError,"ELF architecture"):
                b.check_binary_header(p,host=True)
            host=bytearray(guest)
            host[4]=2
            struct.pack_into("<H",host,18,62)
            p.write_bytes(host)
            b.check_binary_header(p,host=True)
            with self.assertRaisesRegex(ValueError,"ELF architecture"):
                b.check_binary_header(p,host=False)

    def test_missing_or_symlinked_binary_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"missing"
            with self.assertRaisesRegex(ValueError,"regular non-symlink"):
                b.require_regular(p)
            real=Path(tmp)/"real"
            real.write_bytes(b"x")
            p.symlink_to(real)
            with self.assertRaisesRegex(ValueError,"regular non-symlink"):
                b.require_regular(p)

    def test_checksum_list_fixed_three_members(self):
        values={b.ELF:"a"*64,b.QEMU:"b"*64,b.FDT:"c"*64}
        sums=b.build_checksums(b.DIR,values).splitlines()
        self.assertEqual(len(sums),3)
        self.assertEqual([line.split("  ")[1] for line in sums],
                         [b.ELF,b.QEMU,b.FDT])

    def test_qemu_baseline_source_pin_matches_repository_gitlink(self):
        b.gitlink_pin()


if __name__=="__main__":
    unittest.main(verbosity=2)
