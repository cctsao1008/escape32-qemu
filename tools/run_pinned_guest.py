#!/usr/bin/env python3
"""Execute unchanged native Guest regression using verified pinned pair.

Nothing is compiled or written to Guest. Any ABI/dependency mismatch
causes an explicit error; never silently fall back to a local QEMU/ELF.
The original test and its strict acceptance switches are passed through.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from e62_pinned_baseline import DIR, ELF, QEMU, verify

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--":
        args = args[1:]
    if ("--elf" in args or "--qemu" in args or
            any(x.startswith("--elf=") or x.startswith("--qemu=")
                for x in args)):
        raise SystemExit("Pinned runner refuses overridden --elf / --qemu")
    verify(smoke=True)
    env = os.environ.copy()
    runtime = str(DIR / "qemu/linux-x86_64")
    env["LD_LIBRARY_PATH"] = runtime + (
        ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    command = [
        sys.executable,
        str(ROOT / "tests/g13b2_native_drive_probe.py"),
        "--qemu", str(DIR / QEMU),
        "--elf", str(DIR / ELF),
        *args,
    ]
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
