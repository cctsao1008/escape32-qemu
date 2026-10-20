#!/usr/bin/env python3
"""G9a: MCPWM4 native AQ/compare/shadow and read-only six-output observer.

No firmware patch and no prefilled output duty: every level is evaluated
from the guest-visible MCPWM register image and virtual counter.
"""
import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from g0_memory import QTest

SYS = 0x400af000
POWER, TBCLKSYNC = SYS + 0x1424, SYS + 0x148c
PWM = 0x40014000
OBS = 0x5ffe1000
PERIOD, SHADOW, CTL, COUNTER = PWM+0x14, PWM+0x18, PWM+0x10, PWM+0x28

def run(qemu, elf, sim, check, machine_extra=""):
    with tempfile.TemporaryDirectory(prefix="am13e-g9-") as td:
        sock = os.path.join(td, "qtest.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(sock)
            server.listen(1)
            server.settimeout(15)
            proc = subprocess.Popen([
                str(qemu), "-machine",
                "am13e23019,accel=qtest,esc-sim=" + ("on" if sim else "off") + machine_extra,
                "-kernel", str(elf), "-display", "none", "-serial", "none",
                "-monitor", "none", "-qtest", "unix:path=" + sock,
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                conn, _ = server.accept()
                with conn:
                    check(QTest(conn))
            finally:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                errors = proc.stderr.read()
                proc.stderr.close()
    return errors

def set_pwm_pair(q, pair, compare, aq, shadow=False):
    base = PWM + 0x100 + pair * 0x200
    off = 4 if shadow else 0
    q.write(base + 0x00 + off, compare[0])
    q.write(base + 0x08 + off, compare[1])
    q.write(base + 0x20 + off, aq[0])
    q.write(base + 0x28 + off, aq[1])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", required=True, type=Path)
    ap.add_argument("--elf", required=True, type=Path)
    args = ap.parse_args()
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for p in (qemu, elf):
        if not p.is_file():
            ap.error("Missing file: " + str(p))

    def functional(q):
        assert q.read(OBS) & 1 == 0
        assert q.read(CTL) == 2      # STOP/FREEZE at reset
        assert q.read(OBS + 0x10) == 0
        assert q.read(POWER) & 0x200 == 0  # TI PWM4 reset power OFF
        q.write(CTL, 0)                   # deliberately unpowered TBCTL
        assert q.read(CTL) == 2           # rejected, never fabricated
        print("G9_UNPOWERED_TBCTL_WRITE_REJECTED=PASS")
        q.write(POWER, 0x26000200)  # PWM4 power bit 9
        assert q.read(POWER) & 0x200

        # Set three independent phase-leg images. A=25%/40%/60%
        # rising at ZERO and falling at compare A; B forced low.
        q.write(PERIOD, 99)
        q.write(SHADOW, 99)
        set_pwm_pair(q, 0, (25, 1), (0x12, 0x1))
        set_pwm_pair(q, 1, (40, 1), (0x12, 0x1))
        set_pwm_pair(q, 2, (60, 1), (0x12, 0x1))
        q.write(CTL, 0)  # UP; TBCLKSYNC still disabled
        assert q.read(OBS) & 1 == 0
        assert q.read(OBS + 0x18) == 0
        q.cmd("clock_step 2000")
        assert q.read(COUNTER) == 0
        print("G9_PWM_TBCLKSYNC_GATES_COUNTER=PASS")

        q.write(TBCLKSYNC, 1)
        assert q.read(OBS) & 0xF == 0xF
        assert q.read(OBS + 0x08) == 100
        high = [q.read(OBS + 0x18 + 4*i) for i in range(6)]
        assert high == [25, 0, 40, 0, 60, 0], high
        assert q.read(OBS + 0x14) == 0x3F
        print("G9_SIX_AQ_OUTPUT_DUTY_25_0_40_0_60_0=PASS")

        # Independent RED on A (2 ticks) + independent FED on
        # B (2 ticks) with SDK FED input source PWMB.
        q.write(PWM + 0xD4, 2)    # DBRED
        q.write(PWM + 0xD0, 2)    # DBFED
        q.write(PWM + 0xC0, 0x23) # A-RED, B-FED, B-source
        q.write(PWM + 0x128, 0x102) # B HIGH at ZERO, LOW at CMPB
        q.write(PWM + 0x108, 50)
        assert q.read(OBS + 0x14) == 0x3F
        assert q.read(OBS + 0x18) == 23
        assert q.read(OBS + 0x1C) == 52
        q.write(PWM + 0xC0, 0x27) # unsupported inversion
        assert q.read(OBS + 0x14) != 0x3F
        q.write(PWM + 0xC0, 0)
        q.write(PWM + 0x128, 1)
        q.write(PWM + 0x108, 1)
        print("G9_INDEPENDENT_RED_FED_DUTY_AND_INVALID_TOPOLOGY=PASS")

        # The original FW writes all six SHADOW registers, arms
        # one-shot GLD, then an actual Counter ZERO loads the image.
        q.write(PWM + 0xF0, 3)       # GLD=1, OSHTMODE=1, ZERO
        set_pwm_pair(q, 0, (50, 1), (0x12, 0x1), shadow=True)
        set_pwm_pair(q, 1, (50, 1), (0x12, 0x1), shadow=True)
        set_pwm_pair(q, 2, (50, 1), (0x12, 0x1), shadow=True)
        q.write(PWM + 0xF4, 1)       # OSHTLD latch
        assert q.read(PWM + 0xF8) == 1
        assert q.read(PWM + 0x100) == 25   # old active remains
        q.cmd("clock_step 999")
        assert q.read(PWM + 0x100) == 25
        q.cmd("clock_step 1")
        assert q.read(PWM + 0x100) == 50
        assert q.read(PWM + 0x300) == 50
        assert q.read(PWM + 0x500) == 50
        assert q.read(PWM + 0xF8) == 0
        assert [q.read(OBS + 0x18 + 4*i) for i in range(6)] == [
            50, 0, 50, 0, 50, 0]
        print("G9_SHADOW_LOAD_ONLY_AT_REAL_COUNTER_ZERO=PASS")

        # An unlatched image must not change active outputs.
        set_pwm_pair(q, 0, (80, 1), (0x12, 0x1), shadow=True)
        q.cmd("clock_step 1000")
        assert q.read(PWM + 0x100) == 50
        # Re-arm, verify pending interrupt cannot appear merely
        # because INTEN was written; ZERO event asserts it.
        q.write(PWM + 0x98, 8)
        q.write(PWM + 0x90, 8)
        q.write(PWM + 0x84, 1)
        assert q.read(PWM + 0x94) == 0
        q.cmd("clock_step 1000")
        assert q.read(PWM + 0x94) & 8
        q.write(PWM + 0x98, q.read(PWM + 0x98) | 8)
        assert q.read(PWM + 0x94) == 0
        print("G9_MCPWM4_ZERO_EVENT_IRQ_CLEAR=PASS")

        # Disable the timebase: output observer must report zero
        # DRIVE, without altering the firmware-authored compare.
        q.write(TBCLKSYNC, 0)
        assert q.read(OBS + 0x04) == 0
        assert q.read(OBS + 0x18) == 0
        assert q.read(PWM + 0x100) == 50
        print("PASS_G9A_MCPWM4_OUTPUT_OBSERVER_NO_SYNTHETIC_MOTOR=PASS")

    sim_errors = run(qemu, elf, True, functional)
    assert "G9_MCPWM4_POWER_OFF_WRITE" in sim_errors, sim_errors

    def strict(q):
        q.read(OBS)
        q.write(PWM + 0x10, 0)

    err = run(qemu, elf, False, strict)
    assert "G9_UNMODELED_MCPWM4" in err, err
    print("PASS_G9_STRICT_MODE_NO_MCPWM4_SHIM")

if __name__ == "__main__":
    main()
