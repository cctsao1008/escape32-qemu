#!/usr/bin/env python3
"""G12 SYSCTL.RSTCAUSE ID[4:0] TI SDK read-to-clear semantics.

The handoff model knows no prior silicon cause by default; it must not
invent POR, BOOTRST, or WWDT failure. Nonzero test input is an explicit
machine fixture, never a guest write to the real read-only register.
"""
import argparse
from pathlib import Path
from g9_mcpwm_observer import run

SYS_RSTCAUSE = 0x400b0220
SYS_UNMODELED = SYS_RSTCAUSE + 4

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    a = p.parse_args()
    qemu, elf = a.qemu.resolve(), a.elf.resolve()

    def no_history(q):
        assert q.read(SYS_RSTCAUSE) == 0
        assert q.read(SYS_RSTCAUSE) == 0
        print("G12_RSTCAUSE_NO_FABRICATED_RESET_HISTORY=PASS")

    run(qemu, elf, True, no_history)

    def explicit_watchdog_history(q):
        assert q.read(SYS_RSTCAUSE) == 0x0e, "Expected explicit WWDT0 fixture"
        assert q.read(SYS_RSTCAUSE) == 0, "RSTCAUSE.ID must clear after read"
        q.write(SYS_RSTCAUSE, 0x0e)
        assert q.read(SYS_RSTCAUSE) == 0, "Guest cannot forge reset cause"
        print("G12_RSTCAUSE_EXPLICIT_BOOTWWDT_READ_TO_CLEAR=PASS")
        q.read(SYS_UNMODELED)

    errors = run(qemu, elf, True, explicit_watchdog_history,
                 machine_extra=",esc-sim-reset-cause=0xe")
    assert "G2_UNMODELED_SYSCTL write 0x400b0220" in errors, errors
    print("G12_RSTCAUSE_WRITE_REJECTED_RESERVED_UNMODELED=PASS")

    def strict(q):
        assert q.read(SYS_RSTCAUSE) == 0
        q.write(SYS_RSTCAUSE, 0x01)
        assert q.read(SYS_RSTCAUSE) == 0
    errors = run(qemu, elf, False, strict)
    assert "G2_UNMODELED_SYSCTL write 0x400b0220" in errors, errors
    print("PASS_G12_NATIVE_SYSCTL_RSTCAUSE_RTC_STRICT_NO_PHANTOM")

if __name__ == "__main__":
    main()
