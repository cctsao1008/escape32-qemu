#!/usr/bin/env python3
"""E62 G13B3 immutable ELF + QEMU + essential libfdt pinned baseline.

This file does NOT build firmware or emulator, change Guest state or
"bless" the known-failing twelve-sector / 90ms rotor gate. Packaging is
explicit and accepts only a bit-identical SHA-pinned CI fast-ramp ELF.
QEMU is the paired, machine-source-cache-keyed Ubuntu 24.04 binary;
a QTest and the unchanged original-Guest six-sector gate are run on
the *packaged files* BEFORE repository commit.

Public redistributors must independently honor ESCape32 GPL-3.0 and
the particular compiled TI SDK components' redistribution notices.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "baseline/e62-g13b3"
ELF = "firmware/AM13E-rev17.3.elf"
QEMU = "qemu/linux-x86_64/qemu-system-arm"
FDT = "qemu/linux-x86_64/libfdt.so.1"
MANIFEST = "manifest.json"
CHECKSUMS = "SHA256SUMS"
EXPECTED_ELF_SHA256 = (
    "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
)
QEMU_UPSTREAM_COMMIT = "44f28df24767cf9dca1ddc9b23157737c4cbb645"
ESCAPE32_SOURCE_COMMIT = "b0204670515d2de0b2480b52273038f1ee13d30a"
TI_SDK_COMMIT = "b872469ceef18de5e39a1d3acb0821ec158b44c7"
SOURCE_FILES = (
    "build.sh",
    "machine/am13e23019.c",
    "machine/am13e_motor_feedback.inc",
    "machine/am13e_trip_safety.inc",
    "machine/am13e_pa26_waveform.inc",
    "machine/am13e_pwm_history.inc",
    "tests/fixtures/g13b2_sim_only_board.cmake",
    "tests/fixtures/g13b3l_sim_only_ramp.cmake",
)
MAX_GIT_FILE_BYTES = 95_000_000


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as inp:
        for block in iter(lambda: inp.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require_regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected regular non-symlink binary: {path}")


def gitlink_pin():
    result = subprocess.check_output(
        ["git", "ls-tree", "HEAD", "qemu"], cwd=ROOT, text=True
    ).strip()
    entries = result.split()
    if (len(entries) != 4 or entries[0] != "160000" or
            entries[1] != "commit" or entries[2] != QEMU_UPSTREAM_COMMIT):
        raise ValueError("QEMU gitlink no longer pins exact 6.2.0 commit")


def check_binary_header(path: Path, *, host: bool):
    require_regular(path)
    data = path.open("rb").read(64)
    # QEMU host target: little endian AMD64 ELF64.
    # Original ESCape32: little endian ARM ELF32.
    required = (2, 62) if host else (1, 40)
    if (data[:4] != b"\x7fELF" or data[5] != 1 or
            data[4] != required[0] or
            struct.unpack_from("<H", data, 18)[0] != required[1]):
        raise ValueError("ELF architecture does not match pinned baseline " +
                         str(path))


def source_hashes() -> dict[str, str]:
    return {f: digest(ROOT / f) for f in SOURCE_FILES}


def build_checksums(directory: Path, hashes: dict[str, str]):
    return "".join(f"{hashes[k]}  {k}\n" for k in (ELF, QEMU, FDT))


def stage(elf: Path, qemu: Path, fdt: Path, *, source_run: str):
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("Baseline packaging runs only on Linux x86_64")
    gitlink_pin()
    for path in (elf, qemu, fdt):
        require_regular(path)
    check_binary_header(elf, host=False)
    check_binary_header(qemu, host=True)
    if digest(elf) != EXPECTED_ELF_SHA256:
        raise ValueError("Refusing locally rebuilt/unapproved fast-ramp Guest ELF")
    for rel, src in ((ELF, elf), (QEMU, qemu), (FDT, fdt)):
        dest = DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    # The exact cached QEMU executable is preferred. If it exceeds
    # GitHub's per-object limit, remove only debugging information
    # without changing executable code. Retest the packaged QEMU below.
    packaging = "BYTE_IDENTICAL_CI_QEMU_EXECUTABLE"
    if (DIR / QEMU).stat().st_size > MAX_GIT_FILE_BYTES:
        subprocess.run(["strip", "--strip-debug", str(DIR / QEMU)], check=True)
        packaging = "CI_QEMU_STRIP_DEBUG_RETEST_PACKAGED_EXECUTABLE"
    if (DIR / QEMU).stat().st_size > MAX_GIT_FILE_BYTES:
        raise ValueError("QEMU still too large for direct Git; DO NOT use LFS implicitly")
    (DIR / QEMU).chmod(0o755)
    hashes = {p: digest(DIR / p) for p in (ELF, QEMU, FDT)}
    binary_sizes = {p: (DIR / p).stat().st_size for p in (ELF, QEMU, FDT)}
    manifest = {
        "schema": "e62-g13b3-paired-binary-baseline.v1",
        "id": "E62-G13B3-SIM_ONLY-UBUNTU24-X86_64-v1",
        "platform": {
            "host": "Ubuntu 24.04 x86_64 ABI",
            "guest": "AM13E23019 Cortex-M33 original ESCape32 Rel17.3",
            "runtime_note": "glibc and other host SONAME dependencies must resolve",
        },
        "files": {
            p: {"sha256": hashes[p], "size_bytes": binary_sizes[p]}
            for p in (ELF, QEMU, FDT)
        },
        "qemu": {
            "upstream_revision": QEMU_UPSTREAM_COMMIT,
            "packaging": packaging,
            "test_machine": "am13e23019,esc-sim=on",
            "source_tree_sha256": source_hashes(),
        },
        "guest": {
            "source_repo": "https://github.com/cctsao1008/ESCape32",
            "source_revision": ESCAPE32_SOURCE_COMMIT,
            "ti_sdk_repo": "https://github.com/TexasInstruments/am13e2x_sdk",
            "ti_sdk_revision": TI_SDK_COMMIT,
            "toolchain": "Ubuntu 24.04 gcc-arm-none-eabi 13 (source CI cache)",
            "profile": "tests/fixtures/g13b3l_sim_only_ramp.cmake",
            "flags": {
                "G13B2_SIM_ONLY_OPT_IN": True,
                "G13B2_SIM_ONLY_IDEAL_BEMF_REFERENCE": True,
            },
        },
        "provenance": {
            "first_verified_source_run":
                "https://github.com/cctsao1008/escape32-qemu/actions/runs/40107025185",
            "packaging_run": source_run,
            "recorded_g13b3l_six_sector": "PASS",
            "recorded_g13b3m_90ms_rotor": "FAIL_ORIGINAL_REVERSE_MOTION",
            "packaged_binary_qtest_and_native_gate":
                "MUST_PASS_BEFORE_COMMIT_BY_PUBLISH_WORKFLOW",
        },
        "limits": {
            "sim_only": True,
            "real_mosfet_waveform_qualified": False,
            "native_rotor_90ms_qualified": False,
            "physical_motor_calibrated": False,
        },
        "notices": "See baseline/e62-g13b3/README.md for upstream licenses",
    }
    (DIR / MANIFEST).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    (DIR / CHECKSUMS).write_text(build_checksums(DIR, hashes))
    verify(smoke=True)
    print("PASS_G13B3_STAGED_PINNED_BINARY_PAIR " +
          json.dumps({
              "files": hashes, "bytes": binary_sizes,
              "qemu_packaging": packaging,
              "source_run": source_run,
          }, sort_keys=True), flush=True)


def verify(*, smoke=False):
    gitlink_pin()
    mpath = DIR / MANIFEST
    require_regular(mpath)
    metadata = json.loads(mpath.read_text())
    if (metadata.get("schema") != "e62-g13b3-paired-binary-baseline.v1"
        or metadata.get("id") != "E62-G13B3-SIM_ONLY-UBUNTU24-X86_64-v1"
        or metadata["qemu"]["upstream_revision"] != QEMU_UPSTREAM_COMMIT
        or metadata["guest"]["source_revision"] != ESCAPE32_SOURCE_COMMIT
        or metadata["guest"]["ti_sdk_revision"] != TI_SDK_COMMIT):
        raise ValueError("Manifest identity/source revision mismatch")
    if metadata["qemu"]["source_tree_sha256"] != source_hashes():
        raise ValueError("Pinned QEMU/Guest build source drift: republish binary pair")
    hashes = {}
    if set(metadata["files"]) != {ELF, QEMU, FDT}:
        raise ValueError("Unexpected pinned binary contents")
    for p in (ELF, QEMU, FDT):
        path = DIR / p
        require_regular(path)
        if path.stat().st_size != metadata["files"][p]["size_bytes"]:
            raise ValueError("Pinned binary size changed: " + p)
        actual = digest(path)
        if actual != metadata["files"][p]["sha256"]:
            raise ValueError("Pinned binary SHA256 mismatch: " + p)
        hashes[p] = actual
    if hashes[ELF] != EXPECTED_ELF_SHA256:
        raise ValueError("Pinned Guest does not match the original CI-tested ELF")
    if (DIR / CHECKSUMS).read_text() != build_checksums(DIR, hashes):
        raise ValueError("SHA256SUMS do not match verified pair")
    check_binary_header(DIR / ELF, host=False)
    check_binary_header(DIR / QEMU, host=True)
    if not os.access(DIR / QEMU, os.X_OK):
        raise ValueError("Pinned QEMU binary missing executable mode")
    if smoke:
        if platform.system() != "Linux" or platform.machine() != "x86_64":
            raise ValueError("Pinned QEMU is only for Linux x86_64")
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = str(DIR / "qemu/linux-x86_64") + (
            ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        machine = subprocess.run(
            [str(DIR / QEMU), "-M", "help"], capture_output=True,
            text=True, timeout=15, env=env, check=True)
        if "am13e23019" not in machine.stdout:
            raise ValueError("Pinned executable missing expected AM13E Machine")
        ld = subprocess.run(
            ["ldd", str(DIR / QEMU)], capture_output=True, text=True,
            timeout=15, env=env, check=True)
        if "not found" in ld.stdout:
            raise ValueError("Pinned QEMU host runtime contains unresolved dependencies")
    print("PASS_E62_G13B3_PINNED_BINARY_PAIR_SHA256_AND_SOURCE " +
          json.dumps(hashes, sort_keys=True), flush=True)
    return metadata


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="command", required=True)
    stagep = sp.add_parser("stage")
    stagep.add_argument("--elf", type=Path, required=True)
    stagep.add_argument("--qemu", type=Path, required=True)
    stagep.add_argument("--libfdt", type=Path, required=True)
    stagep.add_argument("--source-run", required=True)
    verify_p = sp.add_parser("verify")
    verify_p.add_argument("--smoke-qemu", action="store_true")
    args = p.parse_args()
    if args.command == "stage":
        stage(args.elf, args.qemu, args.libfdt, source_run=args.source_run)
    else:
        verify(smoke=args.smoke_qemu)


if __name__ == "__main__":
    main()
