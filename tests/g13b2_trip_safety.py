#!/usr/bin/env python3
"""G13B2B QTest: independently modeled physical OC / nFAULT -> OST.

No original ELF arm/motor PASS is implied. QTest programs test electrical
routes; checks that the *real modeled* routed physical fault remains
latched despite CPU-independent W1C and suppresses all PWM output levels.
The signal fixtures are physical current ADC-like codes and PA22 nFAULT
levels, never fake OST flags, QEMU IRQ injection or ready bits.
"""
import argparse
from pathlib import Path
from g9_mcpwm_observer import run, set_pwm_pair
from g10_feedback import readw, writew

SYS_PWR = 0x400b0424
GPIO0_PWR = 0x400f0800
PINCM = 0x400cc000
XBAR_IN = 0x40468000
XBAR_PWM = 0x40469000
PWM = 0x40014000
OBS = 0x5ffe1000
STIM = 0x5ffe5000
OST2, OST3 = 0x20000, 0x40000
OC_CMP = [0x40461000, 0x40462000, 0x40463000]


def qualified(q):
    q.write(SYS_PWR, 0x26003a00)  # PWM4 bit9; CMPSS1/2/3 bits11-13
    assert q.read(SYS_PWR) & 0x3a00 == 0x3a00
    q.write(GPIO0_PWR, 0x26000001)
    # Native SYSCTL.CMPHPMXSEL packed fields: CMPSS1 HP1,
    # CMPSS2 HP3, CMPSS3 HP1 (true three independent inputs).
    q.write(0x400b0444, (1 << 3) | (3 << 6) | (1 << 9))
    assert q.read(0x400b0444) == 0x2c8
    q.write(PINCM + 4*22, 0x00040081)  # PA22 true GPIO input
    assert q.read(PINCM + 4*22) & 0x400bf == 0x40081
    # Independently configure all three real CMPSS CTRIPH high sources.
    for index, base in enumerate(OC_CMP):
        writew(q, base + 0x08, 0)   # DAC updates via MCLK
        writew(q, base + 0x0c, 2048)
        writew(q, base + 0x24, 0)
        q.write(STIM + index*4, 0x10000 | 1000)
        writew(q, base + 0x00, 0x8000)  # DACH, enabled, async CTRIPH
        assert readw(q, base + 0x0e) == 2048
    # Board electrical routes exactly match original firmware:
    # PA22 / INPUTXBAR2 / PWM TRIP2 OST2
    q.write(XBAR_IN + 0x04, 22)
    q.write(XBAR_IN + 0x410, 1 << 22)
    q.write(XBAR_PWM + 0x140, 1 << 21)
    q.write(XBAR_PWM + 0x180, 0x54)  # CMPSS1+2+3 CTRIPH
    q.write(XBAR_PWM + 0x30, 1 << 1) # active-low PA22 inverted
    q.write(PWM + 0xac, 0xa)         # TZA=B LOW physical trip override
    q.write(PWM + 0x90, 0x04)        # OST actual native interrupt enable
    q.write(PWM + 0xa0, OST2 | OST3)
    assert q.read(XBAR_PWM + 0x140) == 0x200000
    assert q.read(XBAR_PWM + 0x180) == 0x54
    assert q.read(PWM + 0xa0) == (OST2 | OST3)
    assert q.read(PWM + 0xb0) == 0
    assert q.read(STIM + 0x10) == 0  # all external levels healthy
    print("PASS_G13B2B_THREE_NATIVE_OC_AND_NFAULT_ROUTES_ARMED")


def motor_pwm_image(q):
    q.write(PWM + 0x14, 99)
    q.write(PWM + 0x18, 99)
    set_pwm_pair(q, 0, (50, 1), (0x12, 0x1))
    set_pwm_pair(q, 1, (60, 1), (0x12, 0x1))
    set_pwm_pair(q, 2, (70, 1), (0x12, 0x1))
    q.write(PWM + 0x10, 0)
    q.write(0x400b048c, 1)
    assert q.read(OBS) & 0xf == 0xf
    assert [q.read(OBS + 0x18 + 4*i) for i in range(6)] == [
        50, 0, 60, 0, 70, 0]
    print("G13B2B_TEST_ONLY_THREE_PHASE_PWM_OBSERVER_VALID")


def run_test(q):
    assert q.read(PWM + 0xb0) == 0
    assert q.read(STIM + 0x10) == 0
    assert q.read(STIM + 0x14) == 0
    qualified(q)
    motor_pwm_image(q)

    # (1) nFAULT physical assertion produces genuine OST2 even with no
    # guest CPU running. W1C while nFAULT LOW must immediately relatch.
    q.write(STIM + 0x18, 1)
    assert q.read(STIM + 0x18) == 1
    assert q.read(STIM + 0x10) & 2
    assert q.read(PWM + 0xb0) & OST2
    assert q.read(PWM + 0x94) & 0x04
    assert [q.read(OBS + 0x18 + 4*i) for i in range(6)] == [0]*6
    q.write(PWM + 0xb4, OST2)
    assert q.read(PWM + 0xb0) & OST2, "Cannot clear asserted physical nFAULT"
    q.write(STIM + 0x18, 0)
    assert q.read(PWM + 0xb0) & OST2, "OST latched after fault release"
    q.write(PWM + 0xb4, OST2)
    assert q.read(PWM + 0xb0) & OST2 == 0
    assert q.read(PWM + 0x94) & 0x04 == 0
    print("PASS_G13B2B_PA22_NFAULT_OST2_ASYNC_LATCH_W1C_PHYSICAL_RELEASE")

    # (2) Each independently sampled analog input must assert OST3.
    for phase in range(3):
        q.write(STIM + 4*phase, 0x10000 | 3000)
        assert q.read(STIM + 0x10) & 4, f"OC phase={phase} did not trip"
        assert q.read(PWM + 0xb0) & OST3, f"OST3 missed OC phase={phase}"
        assert [q.read(OBS + 0x18 + 4*i) for i in range(6)] == [0]*6
        q.write(PWM + 0xb4, OST3)
        assert q.read(PWM + 0xb0) & OST3, "W1C bypassed active analog OC"
        q.write(STIM + 4*phase, 0x10000 | 1000)
        assert q.read(PWM + 0xb0) & OST3, "OC latch cleared on level alone"
        q.write(PWM + 0xb4, OST3)
        assert q.read(PWM + 0xb0) & OST3 == 0
    print("PASS_G13B2B_THREE_PHASE_OC_OST3_ASYNC_LATCH_AND_W1C")

    # (3) Unknown current fixture is NOT healthy; missing sensor
    # still latches OST3. Writing direct status is never accepted.
    q.write(STIM, 0)
    assert q.read(PWM + 0xb0) & OST3
    q.write(PWM + 0xb0, 0)  # status is read-only, must fail closed
    assert q.read(PWM + 0xb0) & OST3
    q.write(STIM, 0x10000 | 1000)
    q.write(PWM + 0xb4, OST3)
    assert q.read(PWM + 0xb0) & OST3 == 0
    assert [q.read(OBS + 0x18 + 4*i) for i in range(6)] == [
        50, 0, 60, 0, 70, 0]
    print("PASS_G13B2B_INVALID_OC_INPUT_NOT_HEALTHY_AND_STATUS_READONLY")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    args = p.parse_args()
    for file in (args.qemu, args.elf):
        if not file.is_file():
            p.error("Missing QEMU or original ELF")
    errors = run(args.qemu.resolve(), args.elf.resolve(), True, run_test)
    assert "G9_UNMODELED_MCPWM4 write 0x400140b0" in errors, errors[-2500:]
    print("PASS_G13B2B_QTEST_SIM_ONLY_PHYSICAL_TRIP_MODEL_NOT_NATIVE_ARMING")


if __name__ == "__main__":
    main()
