#!/usr/bin/env python3
"""G14 QTest RED/FED carrier-boundary counterexample; DEVICE MODEL ONLY.

The historical 0x28 -> 0x38 -> 0x10 was a same-time ZERO/Shadow
model overlap. This fixture exercises the actual rebuilt QEMU MCPWM
register/timer path, not a Python substitute and not original Guest.
With RED removed (OUT_MODE=01, FED only), a genuine complementary
overlap MUST remain observable (no clipping or rule waiver).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from g9_mcpwm_observer import (
    run, set_pwm_pair, POWER, TBCLKSYNC, PWM, PERIOD, SHADOW, CTL)
from tools.native_pwm_history import read_native_pwm_history


def fixture(q, *, mode):
    assert mode in ("red_fed", "red_only", "fed_only")
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
    # A real GLD ZERO also transfers DB shadow registers. Keep the
    # intended delays stable instead of accidentally loading zeros.
    q.write(PWM + 0xd8, 2)  # DBFEDS
    q.write(PWM + 0xdc, 2)  # DBREDS
    q.write(PWM + 0xc0, {"red_fed":0x23, "red_only":0x22,
                           "fed_only":0x21}[mode])
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

    # OUT_MODE=11: both RED and FED, delayed B-low remains asserted
    # while W-high is delayed. OUT_MODE=10: RED only, low switches off
    # immediately and high waits 20 ns. OUT_MODE=01: FED only, high
    # becomes asserted immediately while W-low remains on (unsafe).
    zero_expected = {"red_fed":0x28,"red_only":0x00,"fed_only":0x38}[mode]
    assert zero[0].new_mask == zero_expected, (mode,zero[0])
    assert shadow[0].new_mask == zero_expected, (mode,shadow[0])
    assert at_zero.current_internal_sixbit_mask == zero_expected

    q.cmd("clock_step 20")  # exactly two TBCLK ticks
    after = read_native_pwm_history(q.read)
    edges = [x for x in after.observed_events
             if x.kind == "QEMU_CLOCKED_AQ_DB_EDGE"
             and x.virtual_ns >= zero[0].virtual_ns]
    assert edges, after
    assert edges[0].virtual_ns == zero[0].virtual_ns + 20, edges
    assert edges[0].new_mask == 0x10, edges
    assert after.current_internal_sixbit_mask == 0x10
    overlapping = [x for x in after.observed_events
                   if x.virtual_ns >= zero[0].virtual_ns
                   and (x.new_mask & 0x30) == 0x30]
    if mode == "fed_only":
        assert overlapping, after
        print("PASS_G14_UNSAFE_FED_ONLY_STILL_REPORTS_W_OVERLAP")
    else:
        assert not overlapping, (mode,overlapping)
        print("PASS_G14_ZERO_SHADOW_" + mode.upper() +
              "_20NS_CONTINUITY")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    a = p.parse_args()
    for path in (a.qemu, a.elf):
        if not path.is_file():
            p.error("Missing QEMU or unchanged original ELF: " + str(path))
    for mode in ("red_fed", "red_only", "fed_only"):
        run(a.qemu.resolve(), a.elf.resolve(), True,
            lambda q, mode=mode: fixture(q, mode=mode))
    print("PASS_G14_QEMU_DEVICE_MODEL_COUNTEREXAMPLE_NOT_NATIVE_ROTOR_GATE")


if __name__ == "__main__":
    main()
