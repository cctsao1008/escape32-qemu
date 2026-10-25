#!/usr/bin/env python3
"""G14 QTest RED/FED carrier-boundary counterexample; DEVICE MODEL ONLY.

The historical 0x28 -> 0x38 -> 0x10 was a same-time ZERO/Shadow
model overlap. This fixture exercises the actual rebuilt QEMU MCPWM
register/timer path, not a Python substitute and not original Guest.
With RED removed, a genuinely conflicting configuration MUST still
expose the overlap (no masking, clipping or rule waiver).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from g9_mcpwm_observer import (
    run, set_pwm_pair, POWER, TBCLKSYNC, PWM, PERIOD, SHADOW, CTL)
from tools.native_pwm_history import read_native_pwm_history


def fixture(q, *, red_enabled):
    q.write(POWER, 0x26000200)
    q.write(PERIOD, 99)
    q.write(SHADOW, 99)
    # U is floating. V-low and W-low are ON in the old ACTIVE
    # image: exact old mask 0x28.
    set_pwm_pair(q, 0, (1, 1), (1, 1))
    set_pwm_pair(q, 1, (1, 1), (1, 2))
    set_pwm_pair(q, 2, (1, 1), (1, 2))
    q.write(PWM + 0xd4, 2)  # A rising delay = 2 TBCLK
    q.write(PWM + 0xd0, 2)  # B falling delay = 2 TBCLK
    q.write(PWM + 0xc0, 0x23 if red_enabled else 0x22)
    q.write(CTL, 0)
    q.write(TBCLKSYNC, 1)
    h = read_native_pwm_history(q.read)
    assert h.latest_internal_model_valid
    assert h.current_internal_sixbit_mask == 0x28, h
    # Next carrier: V-low and W-low deassert at ZERO; W-high
    # asserts. B had been on at the end of the preceding carrier.
    # AQ=0x201 means CLEAR on ZERO, SET on CB=10.
    set_pwm_pair(q, 0, (1, 1), (1, 1), shadow=True)
    set_pwm_pair(q, 1, (1, 10), (1, 0x201), shadow=True)
    set_pwm_pair(q, 2, (1, 10), (2, 0x201), shadow=True)
    q.write(PWM + 0xf0, 3)  # global one-shot ZERO load
    q.write(PWM + 0xf4, 1)
    assert q.read(PWM + 0xf8) == 1

    q.cmd("clock_step 1000")  # 100 x 10ns = first ZERO
    at_zero = read_native_pwm_history(q.read)
    zero = [x for x in at_zero.observed_events
            if x.kind == "QEMU_ORIGINAL_PWM_ZERO_CALLBACK"]
    shadow = [x for x in at_zero.observed_events
              if x.kind == "QEMU_SHADOW_ACTIVE_LOAD"]
    assert len(zero) == 1 and len(shadow) == 1, (zero, shadow)
    assert zero[0].virtual_ns == shadow[0].virtual_ns
    assert zero[0].old_mask == 0x28

    if red_enabled:
        # Prior ACTIVE AQ image must supply the delayed W-high input.
        assert zero[0].new_mask == 0x28, zero[0]
        assert shadow[0].new_mask == 0x28, shadow[0]
        assert at_zero.current_internal_sixbit_mask == 0x28
    else:
        # Deliberate unsafe complementary controls still show overlap.
        assert zero[0].new_mask == 0x38, zero[0]
        assert at_zero.current_internal_sixbit_mask == 0x38

    q.cmd("clock_step 20")  # exactly two TBCLK ticks
    after = read_native_pwm_history(q.read)
    edges = [x for x in after.observed_events
             if x.kind == "QEMU_CLOCKED_AQ_DB_EDGE"
             and x.virtual_ns >= zero[0].virtual_ns]
    assert edges, after
    assert edges[0].virtual_ns == zero[0].virtual_ns + 20, edges
    assert edges[0].new_mask == 0x10, edges
    assert after.current_internal_sixbit_mask == 0x10
    if red_enabled:
        assert all(not (x.new_mask & 0x30) == 0x30
                   for x in after.observed_events
                   if x.virtual_ns >= zero[0].virtual_ns)
        print("PASS_G14_ZERO_SHADOW_PREVIOUS_CARRIER_RED_FED_20NS_CONTINUITY")
    else:
        assert any((x.new_mask & 0x30) == 0x30
                   for x in after.observed_events)
        print("PASS_G14_UNSAFE_NO_RED_STILL_REPORTS_W_COMPLEMENTARY_OVERLAP")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    a = p.parse_args()
    for path in (a.qemu, a.elf):
        if not path.is_file():
            p.error("Missing QEMU or unchanged original ELF: " + str(path))
    for red in (True, False):
        run(a.qemu.resolve(), a.elf.resolve(), True,
            lambda q, red=red: fixture(q, red_enabled=red))
    print("PASS_G14_QEMU_DEVICE_MODEL_COUNTEREXAMPLE_NOT_NATIVE_ROTOR_GATE")


if __name__ == "__main__":
    main()
