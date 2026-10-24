#!/usr/bin/env python3
"""QTest G13B3 actually executed QEMU-clocked internal six-level events.

These time-ordered virtual timer callbacks are not MOSFET gate-voltage
waveform samples. All PWM register writes below are isolated QTest
device-fixture writes, not original Guest firmware execution.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from g9_mcpwm_observer import (
    run,set_pwm_pair,POWER,TBCLKSYNC,PWM,PERIOD,SHADOW,CTL,OBS)
from tools.native_pwm_history import BASE,read_native_pwm_history
from tools.native_pwm_switching_plan import capture_qemu_carrier_plan


def verify(q):
    history=read_native_pwm_history(q.read)
    assert not history.observed_events
    assert not history.qemu_pwm_clock_running
    q.write(POWER,0x26000200)
    q.write(PERIOD,99)
    q.write(SHADOW,99)
    for phase,count in enumerate((25,40,60)):
        set_pwm_pair(q,phase,(count,1),(0x12,1))
    q.write(CTL,0)
    q.write(TBCLKSYNC,1)
    before=read_native_pwm_history(q.read)
    assert before.qemu_pwm_clock_running
    assert before.latest_internal_model_valid
    assert not any(e.kind=="QEMU_CLOCKED_AQ_DB_EDGE"
                   for e in before.observed_events)
    started=before.observed_events[-1].virtual_ns
    plan=capture_qemu_carrier_plan(q.read)
    assert [(e.tick,e.mask_after) for e in plan.edges]==[
        (25,0x14),(40,0x10),(60,0),(100,0x15)]
    # Merely reading the prior ACTIVE-image carrier plan does NOT
    # manufacture any historical QEMU edge events.
    assert read_native_pwm_history(q.read).total_events_since_pmw_reset == (
        before.total_events_since_pmw_reset)
    q.cmd("clock_step 1000")
    h=read_native_pwm_history(q.read)
    edges=[e for e in h.observed_events
           if e.kind=="QEMU_CLOCKED_AQ_DB_EDGE"]
    assert [(e.virtual_ns-started,e.old_mask,e.new_mask)
            for e in edges]==[
                (250,0x15,0x14),(400,0x14,0x10),(600,0x10,0)]
    zeros=[e for e in h.observed_events
           if e.kind=="QEMU_ORIGINAL_PWM_ZERO_CALLBACK"]
    assert len(zeros)==1
    assert zeros[0].virtual_ns-started==1000
    assert zeros[0].old_mask==0 and zeros[0].new_mask==0x15
    assert zeros[0].pwm_counter==0 and zeros[0].native_zero_count==1
    assert h.dropped_events==0
    print("PASS_QEMU_HISTORICAL_AQ_25_40_60_EDGES_AT_VIRTUAL_NS")

    # Shadow registers are not historical output edges until the
    # existing QEMU ZERO loads the original firmware-style latch.
    for phase in range(3):
        set_pwm_pair(q,phase,(50,1),(0x12,1),shadow=True)
    q.write(PWM+0xf0,3)
    q.write(PWM+0xf4,1)
    prior=read_native_pwm_history(q.read)
    assert not any(e.kind=="QEMU_SHADOW_ACTIVE_LOAD"
                   for e in prior.observed_events)
    q.cmd("clock_step 1000")
    after=read_native_pwm_history(q.read)
    shadow=[e for e in after.observed_events
            if e.kind=="QEMU_SHADOW_ACTIVE_LOAD"]
    assert len(shadow)==1, shadow
    assert shadow[0].native_zero_count==2
    assert shadow[0].virtual_ns-started==2000
    print("PASS_QEMU_HISTORICAL_SHADOW_ONLY_AFTER_NATIVE_ZERO")

    # Raw PB13 GPIO/PINCM transitions become labeled boundary records,
    # not physical driver assertion claims.
    q.write(0x400f2000+0x800,0x26000001)
    q.write(0x400cc000+4*45,0x81)
    q.write(0x400f2000+0x12c0,1<<13)
    q.write(0x400f2000+0x1280,1<<13)
    gate=read_native_pwm_history(q.read)
    markers=[e for e in gate.observed_events
             if e.kind=="QEMU_RAW_PB13_GPIO_PINCM_BOUNDARY"]
    assert markers and markers[-1].raw_pb13==1
    assert markers[-1].pb13_doe
    assert markers[-1].pb13_pinmux_valid
    assert not gate.to_dict()["gate_driver_deadtime_measured"]
    print("PASS_QEMU_HISTORICAL_RAW_GATE_GPIO_PINCM_BOUNDARY")

    q.write(TBCLKSYNC,0)
    stopped=read_native_pwm_history(q.read)
    assert not stopped.qemu_pwm_clock_running
    count=stopped.total_events_since_pmw_reset
    print("DIAG_HIST_STOP_TOTAL_BEFORE",count,flush=True)
    q.cmd("clock_step 5000")
    # First check the tiny non-mutating header word independently of
    # a full bounded 128-record read. This isolates timebase failure
    # from history bulk-read failure without weakening the assertion.
    post_total=q.read(BASE+0x14)
    print("DIAG_HIST_STOP_TOTAL_AFTER",post_total,flush=True)
    assert post_total==count, "PWM history changed with TBCLKSYNC disabled"
    print("PASS_QEMU_HISTORICAL_NO_EDGES_WITH_TBCLKSYNC_OFF",flush=True)
    # A stopped clock was already checked against the complete ring
    # immediately before advancing time, and its immutable total
    # header is now checked after advancing. Avoid a redundant long
    # QTest memory scan which can time out after repeated I/O.
    q.write(TBCLKSYNC,1)
    q.cmd("clock_step 60000")
    total=q.read(BASE+0x14)
    retained=q.read(BASE+0x10)
    lost=q.read(BASE+0x1c)
    status=q.read(BASE+0x04)
    print("DIAG_HIST_WRAP_HEADER",{
        "total":total,"retained":retained,"lost":lost,"status":status},
        flush=True)
    assert total>128, "QEMU event callbacks did not fill historical ring"
    assert retained==128 and lost==total-retained
    assert status&4, "Ring overwrite not disclosed in MMIO header"
    # Read both boundary records from the real bounded QEMU ring. The
    # full 128-record causal parser is independently exercised by host
    # tests; no zero/drop or COMPLETE evidence is silently fabricated.
    oldest=BASE+0x80
    newest=BASE+0x80+(127*8)*4
    oldest_ns=q.read(oldest)|(q.read(oldest+4)<<32)
    newest_ns=q.read(newest)|(q.read(newest+4)<<32)
    newest_kind=q.read(newest+8)
    newest_zero=q.read(newest+24)
    assert 0<=oldest_ns<=newest_ns
    assert 1<=newest_kind<=8
    assert newest_zero==q.read(BASE+0x28)
    assert not (status&0x04)==0
    print("PASS_QEMU_HISTORICAL_RING_TRUNCATION_FAIL_CLOSED",flush=True)

    # There is no read/write ack, no reset magic, and no guest state edit
    # through the sideband viewport.
    pval=q.read(PERIOD)
    last=total
    q.write(BASE+8,0)
    assert q.read(PERIOD)==pval
    assert q.read(BASE+0x14)==last
    print("PASS_QEMU_HISTORICAL_READ_ONLY_NO_PWM_REG_MUTATION",flush=True)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--qemu",type=Path,required=True)
    ap.add_argument("--elf",type=Path,required=True)
    a=ap.parse_args()
    for path in (a.qemu,a.elf):
        if not path.is_file():
            ap.error("Missing original test ELF or rebuilt QEMU: "+str(path))
    run(a.qemu.resolve(),a.elf.resolve(),True,verify)
    def strict(q):
        try:
            read_native_pwm_history(q.read)
        except ValueError:
            return
        raise AssertionError("Strict esc-sim=off exposed historical ESC-SIM MMIO")
    run(a.qemu.resolve(),a.elf.resolve(),False,strict)
    print("PASS_G13B3_QEMU_CLOCKED_HISTORY_STRICT_MODE_ISOLATED")


if __name__=="__main__":
    main()
