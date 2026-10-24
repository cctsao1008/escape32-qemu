#!/usr/bin/env python3
"""QTest proof: original QEMU MCPWM4 AQ/DB-derived carrier edge plan.

No original Guest SRAM edits, no spoofed firmware PWM, no motor, no
BEMF/CAP1 injection. The test explicitly writes MCPWM registers as a
QTest device UNIT fixture, not a native Guest firmware validation.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from g9_mcpwm_observer import (
    run, set_pwm_pair, POWER, TBCLKSYNC, PWM, OBS, PERIOD, SHADOW, CTL)
from tools.native_pwm_switching_plan import (
    SWITCH_BASE, capture_qemu_carrier_plan)


def verify(q):
    assert not (q.read(SWITCH_BASE + 4) & 3), (
        "Stopped/power-off machine manufactured carrier edge evidence")
    q.write(POWER,0x26000200)
    q.write(PERIOD,99)
    q.write(SHADOW,99)
    for phase, count in enumerate((25,40,60)):
        set_pwm_pair(q,phase,(count,1),(0x12,0x1))
    q.write(CTL,0)
    q.write(TBCLKSYNC,1)
    # 0x5ffe4000 remains the PA26 external-waveform scheduler. The
    # switch-plan ABI moved to 0x5ffe6000 after discovering a collision.
    assert q.read(0x5ffe4000 + 8) == 0, (
        "Original PA26 queue device was shadowed by switching observer")
    assert q.read(SWITCH_BASE) == 0x50323645, (
        "New switch observer must decode at its distinct address")
    evidence=capture_qemu_carrier_plan(q.read)
    assert evidence.period_ticks == 100
    assert evidence.six_high_ticks == (25,0,40,0,60,0)
    assert [(e.tick,e.mask_after) for e in evidence.edges] == [
        (25,0x14),(40,0x10),(60,0x00),(100,0x15)], evidence
    assert not evidence.original_gate_and_trip_qualified, (
        "QTest register fixture is not native external gate evidence")
    assert evidence.to_dict()["current_continuous_plant_input_qualified"] is False
    print("PASS_QEMU_READONLY_ACTIVE_AQ_MODEL_EDGE_PLAN_25_40_60")

    # Derive modeled independent RED (U high rising delayed) and FED
    # (U low falling delayed) without ever synthesizing physical gates.
    # Complementary AQ pattern: A high [0,25), B high [25,100).
    set_pwm_pair(q,0,(25,25),(0x12,0x201))
    set_pwm_pair(q,1,(1,1),(1,1))
    set_pwm_pair(q,2,(1,1),(1,1))
    q.write(PWM+0xd4,2)
    q.write(PWM+0xd0,2)
    q.write(PWM+0xc0,0x23)
    plan=capture_qemu_carrier_plan(q.read)
    assert plan.six_high_ticks == (23,77,0,0,0,0),plan
    assert [(e.tick,e.mask_after) for e in plan.edges] == [
        (2,1),(25,2)],plan
    print("PASS_QEMU_ACTIVE_AQ_DB_RED_FED_MODEL_EDGE_PLAN")

    # Only ACTIVE registers participate; changing a shadow image with
    # no latch must NOT change the current reconstructed carrier.
    set_pwm_pair(q,0,(80,1),(0x12,1),shadow=True)
    after_shadow=capture_qemu_carrier_plan(q.read)
    assert after_shadow.edges == plan.edges
    assert after_shadow.six_high_ticks == plan.six_high_ticks
    print("PASS_QEMU_SHADOW_UNLATCHED_NO_FALSE_CARRIER_EDGE_CHANGE")

    # Invalid QEMU DB topology fails closed, rather than pretending
    # physical output timings with unknown inversion/cross inputs.
    q.write(PWM+0xc0,0x27)
    try:
        capture_qemu_carrier_plan(q.read)
    except ValueError as e:
        assert "not running/valid" in str(e),repr(e)
    else:
        raise AssertionError("Unsupported AQ/DB topology was silently admitted")
    print("PASS_QEMU_UNMODELED_DB_EDGE_PLAN_FAIL_CLOSED")

    # Unknown addresses and writes to this new observer never change
    # original MCPWM fields or Guest state.
    counter=q.read(PWM+0x14)
    q.write(SWITCH_BASE+0x08,0)
    assert q.read(PWM+0x14)==counter
    print("PASS_QEMU_SWITCH_PLAN_READONLY_NO_PWM_REG_MUTATION")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--qemu",type=Path,required=True)
    p.add_argument("--elf",type=Path,required=True)
    a=p.parse_args()
    if not a.qemu.is_file() or not a.elf.is_file():
        p.error("Built QEMU and original ELF fixture are required")
    errs=run(a.qemu.resolve(),a.elf.resolve(),True,verify)
    if "qemu:" in errs.lower() and "error" in errs.lower():
        # Read-only writes may yield MEMTX_ERROR but not corrupt state.
        print("QEMU stderr retained (includes expected rejected MMIO):",
              errs[:500])
    def strict(q):
        try:
            capture_qemu_carrier_plan(q.read)
        except ValueError:
            return
        raise AssertionError("Strict machine exposed simulator edge plan")
    run(a.qemu.resolve(),a.elf.resolve(),False,strict)
    print("PASS_QEMU_SIM_ONLY_MODEL_EDGE_PLAN_AND_STRICT_ISOLATION")


if __name__=="__main__":
    main()
