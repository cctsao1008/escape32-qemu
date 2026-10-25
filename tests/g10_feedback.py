#!/usr/bin/env python3
"""G10A-C: native ECAP1, 16-bit CMPSS0, virtual-time capture and real edges.

Stimulus register 0x5ffe2000 is explicitly simulator-only and does not
claim a virtual motor, analog comparator delay or silicon calibration.
"""
import argparse
from pathlib import Path
from g9_mcpwm_observer import run

SYS = 0x400af000
POWER = SYS + 0x1424
MUX = SYS + 0x1444
SYNC = SYS + 0x148c
EC = 0x40441000
CMP = 0x40460000
STIM = 0x5ffe2000
PWM = 0x40014000

def readw(q, a):
    return int(q.cmd(f"readw 0x{a:08x}")[1], 0)

def writew(q, a, v):
    q.cmd(f"writew 0x{a:08x} 0x{v:04x}")

def step(q, ns):
    q.cmd(f"clock_step {ns}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", type=Path, required=True)
    ap.add_argument("--elf", type=Path, required=True)
    args = ap.parse_args()

    def functional(q):
        # Reset genuinely unpowered; rejected access is not a fake R/W shim.
        assert q.read(POWER) == 0
        assert q.read(STIM + 12) == 0  # read-only CAPLDEN audit is clear
        q.write(STIM + 12, 1)         # cannot forge guest transition
        assert q.read(STIM + 12) == 0
        q.write(EC + 0x24, 45)
        assert q.read(EC + 0x24) != 45
        q.write(POWER, 0x26000010)  # ECAP1 bit4 only
        assert q.read(EC + 0x00) == 0
        assert readw(q, EC + 0x2a) == 0
        assert readw(q, EC + 0x2c) == 0
        assert readw(q, EC + 0x2e) == 0
        q.write(EC + 0x24, 45)
        assert q.read(EC + 0x24) == 45
        writew(q, EC + 0x28, 0x100)  # CAPLDEN, rising event 1
        assert q.read(STIM + 12) == 0x00010001
        writew(q, EC + 0x28, 0x100)  # idempotent: no false transition
        assert q.read(STIM + 12) == 0x00010001
        writew(q, EC + 0x28, 0)      # subsequent safety-style disable
        assert q.read(STIM + 12) == 0x00010001  # historical bit persists
        writew(q, EC + 0x28, 0x100)
        assert q.read(STIM + 12) == 0x00020001
        print("G10D_CAPLDEN_STICKY_NATIVE_WRITE_AUDIT_NOT_GDB_SAMPLING=PASS")
        writew(q, EC + 0x2c, 2)      # CEVT1 IRQ enable
        assert readw(q, EC + 0x2e) == 0  # enable does not trigger event
        assert q.read(EC + 0x28) == 0x00000100
        writew(q, EC + 0x2a, 0x10)   # TSCTRSTOP bit: free running
        step(q, 1000)
        ts1 = q.read(EC)
        # Original AM13E firmware calibrates the ECAP counter against
        # 200MHz MCLK: 1us corresponds to 200 TSCTR counts.
        assert 200 <= ts1 <= 250, ts1
        print("G13B2E_ECAP1_TSCTR_MCLK200MHZ_1US=PASS")
        assert q.read(EC + 8) == 0
        assert readw(q, EC + 0x2e) == 0
        writew(q, EC + 0x2a, 0)
        ts2 = q.read(EC)
        step(q, 2000)
        assert q.read(EC) == ts2
        writew(q, EC + 0x2a, 0x10)
        step(q, 200)
        assert q.read(EC) > ts2
        print("G10A_ECAP1_POWER_16_32_BIT_REGS_STOP_START_NO_PHANTOM=PASS")

        # Actual 32-bit TSCTR rollover; enable alone must not set CTROVF.
        q.write(EC, 0xfffffff0)
        writew(q, EC + 0x2c, 0x20)
        assert readw(q, EC + 0x2e) == 0
        # 16 counts to 32-bit rollover at 200MHz MCLK: 80ns.
        step(q, 80)
        assert readw(q, EC + 0x2e) & 0x21 == 0x21
        assert q.read(EC) < 10
        writew(q, EC + 0x30, 0x21)
        assert readw(q, EC + 0x2e) == 0
        writew(q, EC + 0x2c, 0x02)
        print("G10B_NATIVE_TSCTR_OVERFLOW_IRQ_AND_W1C=PASS")
        # Dedicated 1ms rate control, independent of any guest flags:
        # original BEMF calibration expects exactly 200,000 counts.
        q.write(EC, 0)
        before_1ms = q.read(EC)
        step(q, 1_000_000)
        after_1ms = q.read(EC)
        assert after_1ms - before_1ms == 200_000, (
            before_1ms, after_1ms)
        print("PASS_G13B2E_ECAP1_MCLK200MHZ_CALIBRATION_COUNTER_RATE")

        # ECFRC is a software flag force, never a timestamp capture.
        writew(q, EC + 0x32, 0x02)
        assert readw(q, EC + 0x2e) & 0x03 == 0x03
        assert q.read(EC + 8) == 0
        writew(q, EC + 0x30, 0x02)
        assert readw(q, EC + 0x2e) == 1
        writew(q, EC + 0x30, 0x01)
        assert readw(q, EC + 0x2e) == 0
        print("G10B_ECFRC_FORCE_FLAG_NOT_CAPTURE_TIMESTAMP=PASS")

        # Explicit phase sample without enabled CMPSS0 cannot create capture.
        q.write(STIM, 0x10000 | 2500)
        step(q, 1000)
        assert q.read(EC + 8) == 0
        assert readw(q, EC + 0x2e) == 0
        q.write(POWER, 0x26000410)
        q.write(MUX, 0)                # COMP HP0 (phase U)
        writew(q, CMP + 0x08, 0)       # DAC active on MCLK
        writew(q, CMP + 0x0c, 2048)
        assert readw(q, CMP + 0x0e) == 2048
        writew(q, CMP + 0x30, 0x420)  # sample window 5, threshold 3
        writew(q, CMP + 0x32, 0)
        writew(q, CMP + 0x72, 0)
        writew(q, CMP, 0x8008)        # COMPDACE, CTRIPH filtered
        step(q, 100)
        assert q.read(EC + 8) != 0    # qualifying HIGH edge captured
        assert readw(q, CMP + 0x04) & 1
        assert readw(q, EC + 0x2e) & 3 == 3
        first = q.read(EC + 8)
        writew(q, EC + 0x30, 3)       # ECCLR W1C flags+global
        assert readw(q, EC + 0x2e) == 0
        step(q, 500)
        assert q.read(EC + 8) == first
        assert readw(q, EC + 0x2e) == 0
        print("G10B_CAPTURE_FROM_QUALIFIED_FILTERED_EDGE_IRQ_W1C=PASS")

        # Glitches shorter than 3 virtual filter samples cannot capture.
        q.write(STIM, 0x10000 | 1500)
        step(q, 10)
        q.write(STIM, 0x10000 | 2500)
        step(q, 100)
        assert readw(q, EC + 0x2e) == 0
        assert q.read(EC + 8) == first
        print("G10C_SHORT_PULSE_REJECTED_NO_SYNTHETIC_CAPTURE=PASS")

        # Falling capture polarity, then change sample across DAC threshold.
        writew(q, EC + 0x28, 0x101)
        q.write(STIM, 0x10000 | 1500)
        step(q, 100)
        assert q.read(EC + 8) > first
        assert readw(q, EC + 0x2e) & 2
        fall_cap = q.read(EC + 8)
        writew(q, EC + 0x30, 3)
        # CAPLDEN=0: event status still asserts but CAP1 must not load.
        writew(q, EC + 0x28, 0)
        q.write(STIM, 0x10000 | 2500)
        step(q, 100)
        assert readw(q, EC + 0x2e) & 2
        assert q.read(EC + 8) == fall_cap
        print("G10C_EDGE_POLARITY_CAPLDEN_DISABLED_STILL_SETS_FLAG=PASS")

        # Wrong capture input selection or comparator power never invents edge.
        writew(q, EC + 0x30, 3)
        writew(q, EC + 0x28, 0x101)  # falling edge would qualify
        q.write(EC + 0x24, 44)        # but wrong input excludes it
        q.write(STIM, 0x10000 | 1500)
        step(q, 100)
        assert readw(q, EC + 0x2e) == 0
        q.write(EC + 0x24, 45)
        writew(q, EC + 0x28, 0x100)  # rising edge would qualify
        writew(q, CMP, 0)             # Comparator disabled
        q.write(STIM, 0x10000 | 2500)
        step(q, 100)
        assert readw(q, EC + 0x2e) == 0
        print("G10C_INPUT45_AND_COMPARATOR_POWER_ROUTE_FAIL_CLOSED=PASS")

        # G19: after a selected rising edge, both unrelated phase
        # changes and exact repeated sample writes MUST NOT postpone the
        # already-running majority filter. This was an actual QEMU timing
        # defect, unlike unsupported claims about motor control policy.
        writew(q, CMP, 0)        # ensure known low filtered state
        writew(q, CMP + 0x08, 0)
        writew(q, CMP + 0x0c, 2048)
        writew(q, CMP + 0x30, 0x420)  # threshold=3, 5ns ticks => 15ns
        writew(q, CMP + 0x32, 0)
        writew(q, CMP + 0x72, 0)
        q.write(MUX, 0)
        q.write(EC + 0x24, 45)
        writew(q, EC + 0x28, 0x100) # rising CAP1
        q.write(STIM, 0x10000 | 1500)
        writew(q, CMP, 0x8008)
        step(q, 100)
        assert (readw(q, CMP + 0x04) & 1) == 0
        writew(q, EC + 0x30, 3)
        old_cap = q.read(EC + 8)
        q.write(STIM, 0x10000 | 2500)  # selected raw goes HIGH
        for k in range(4):
            step(q, 4)
            q.write(STIM + 4, 0x10000 | (2100 + k))  # unselected
            q.write(STIM + 8, 0x10000 | (1900 - k))  # unselected
            q.write(STIM, 0x10000 | 2500) # selected no-op
        assert (readw(q, CMP + 0x04) & 1), (
            "G19 filter was restarted by unchanged/unselected BEMF writes")
        assert (readw(q, EC + 0x2e) & 2) and q.read(EC + 8) > old_cap, (
            "G19 genuine comparator CAP1 starved by unrelated phase updates")
        print("PASS_G19_SELECTED_RAW_CHANGE_ONLY_FILTER_UNSELECTED_NOOP")

        # PWM sync DAC: active DAC not updated until a real PWM zero event.
        q.write(POWER, 0x26000610)   # plus PWM4
        writew(q, CMP, 0)
        writew(q, CMP + 0x08, 0x80)
        writew(q, CMP + 0x0c, 3000)
        assert readw(q, CMP + 0x0e) == 2048
        q.write(PWM + 0x14, 99)
        q.write(PWM + 0x10, 0)
        q.write(SYNC, 1)
        step(q, 1000)
        assert readw(q, CMP + 0x0e) == 3000
        print("G10C_DAC_ACTIVE_LOAD_AT_REAL_MCPWM_ZERO=PASS")

        # The diagnostic history is reset only by a peripheral reset.
        assert q.read(STIM + 12) & 1
        q.write(SYS + 0x1428, 0xb1000010)  # ECAP1 reset assert
        assert q.read(STIM + 12) == 0
        print("G10D_ECAP1_RESET_CLEARS_WRITE_AUDIT=PASS")

        # Power removal must freeze ECAP and reject subsequent register writes.
        q.write(POWER, 0x26000000)
        q.write(EC + 0x24, 44)
        assert q.read(EC + 0x24) != 44
        print("PASS_G10A_G10B_G10C_ECAP1_CMPSS0_FEEDBACK_FIXTURE")

    errors = run(args.qemu.resolve(), args.elf.resolve(), True, functional)
    assert "G10_UNMODELED_ECAP1" in errors, errors

    def strict(q):
        q.write(EC + 0x24, 45)
        q.write(CMP, 0x8008)
        q.write(STIM, 0x10000 | 2500)
        q.read(STIM + 12)  # no observer in strict mode
        q.read(EC + 8)  # unpowered/unmodeled access must be logged
    strict_errors = run(args.qemu.resolve(), args.elf.resolve(), False, strict)
    assert "G10_UNMODELED_ECAP1" in strict_errors, strict_errors
    assert "G10_UNMODELED_CMPSS0" in strict_errors, strict_errors
    print("PASS_G10_STRICT_MODE_NO_FEEDBACK_SHIM")

if __name__ == "__main__":
    main()
