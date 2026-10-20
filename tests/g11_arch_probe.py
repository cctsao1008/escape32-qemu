#!/usr/bin/env python3
"""G11A: observational CPU probe; no firmware writes or IRQ injection.

The non-silicon 0x5ffe3000 aperture is *read-only* and esc-sim-only.
The test checks a consistent reset snapshot, not exception correctness.
"""
import argparse
from pathlib import Path
from g9_mcpwm_observer import run

OBS = 0x5ffe3000
MAGIC = 0x47313101

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", required=True, type=Path)
    ap.add_argument("--elf", required=True, type=Path)
    args = ap.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()

    def check(q):
        assert q.read(OBS) == MAGIC
        assert q.read(OBS + 0x04) == 1, "PRIMASK reset must be one"
        assert q.read(OBS + 0x08) == 0, "BASEPRI reset"
        assert q.read(OBS + 0x0c) == 0, "FAULTMASK reset"
        assert q.read(OBS + 0x10) & 3 == 0, "Thread+MSP at reset"
        assert q.read(OBS + 0x14) == q.read(0x6000), "MSP differs from original ELF"
        assert q.read(OBS + 0x1c) == 0, "IPSR must be Thread"
        assert q.read(OBS + 0x24) == (q.read(0x6004) & ~1)
        assert q.read(OBS + 0x28) & 0x01000000, "Thumb state"
        before = tuple(q.read(OBS + 4 * i) for i in range(11))
        # The observer MUST NOT permit rewriting PRIMASK, CONTROL or SP.
        for off in (4, 0x10, 0x14, 0x18, 0x1c, 0x24):
            q.write(OBS + off, 0)
        after = tuple(q.read(OBS + 4 * i) for i in range(11))
        assert after == before, "Observer write changed architectural state"
        print("PASS_G11A_READ_ONLY_CPU_STATE_RESET_PRIMASK_STACKS")

    run(qemu, elf, True, check)
    def strict(q):
        assert q.read(OBS) != MAGIC
        q.write(OBS + 4, 0)
        assert q.read(OBS) != MAGIC

    run(qemu, elf, False, strict)
    print("PASS_G11A_STRICT_NO_CPU_OBSERVER")

if __name__ == "__main__":
    main()
