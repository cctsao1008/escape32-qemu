#!/usr/bin/env python3
"""G14 SIM_ONLY opt-in WWDT0 BOOTRST and immediate hardware safe-off.

QTest owns explicit peripheral stimulus only; this does NOT prove the
original Guest's signal-loss arming, real silicon timing or recovery.
"""
import argparse
from pathlib import Path
from g5_wwdt import run_qtest, PWREN, CTL0, CTL1, FEED, RUN, SYSTEMCFG

SYSCTL_RSTCAUSE=0x400B0220
GPIO1_DOUT=0x400F3280
GPIO1_PWREN=0x400F2800
GPIO1_DOE=0x400F32C0
MCPWM4=0x40014000

def bootrst_device_contract(q):
    # Independent QTest startup, not Guest-owned receiver initialization.
    q.write(GPIO1_PWREN,0x26000001)
    q.write(GPIO1_DOE,1<<13)
    q.write(GPIO1_DOUT,1<<13)
    assert q.read(GPIO1_DOUT)&(1<<13), "Precondition PB13 high not modeled"
    q.write(PWREN,0x26000001)
    q.write(SYSTEMCFG,0x1b000000)  # Boot reset, not NMI
    q.write(CTL1,0xbe000000)
    q.write(CTL0,0xc9000070)  # QEMU 64 LFCLK ticks / 32768Hz
    assert q.read(RUN)==1
    q.cmd("clock_step 1000000")      # before first deadline
    assert q.read(SYSCTL_RSTCAUSE)==0
    q.write(FEED,0xa7)
    q.cmd("clock_step 1500000")      # still before fed deadline
    assert q.read(SYSCTL_RSTCAUSE)==0
    q.cmd("clock_step 600000")       # virtual 3.10ms > fed 2.95ms
    # QEMU reset dispatcher needs a chance to process the request.
    for _ in range(5):
        if q.read(SYSCTL_RSTCAUSE)==0x0e:
            break
        q.cmd("clock_step 1")
    else:
        raise AssertionError("WWDT expiration did not deliver BOOTRST=0x0e")
    assert q.read(GPIO1_DOUT)&(1<<13)==0,"PB13 gate not safe low"
    assert q.read(RUN)==0,"WWDT was not reset"
    assert q.read(SYSTEMCFG)==0,"WWDT reset did not reset SYSCTL"
    assert q.read(MCPWM4+0x10)==2,"PWM not frozen after system reset"
    assert q.read(SYSCTL_RSTCAUSE)==0,"RSTCAUSE read-to-clear broken"
    print("PASS_G14_WWDT_BOOTRST_0x0E_GATE_SAFE_OFF_AND_PWM_FREEZE")

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--qemu',type=Path,required=True)
    p.add_argument('--elf',type=Path,required=True)
    a=p.parse_args()
    stderr=run_qtest(a.qemu.resolve(),a.elf.resolve(),True,
                      bootrst_device_contract,
                      machine_options=',esc-sim-wwdt-bootrst=on')
    assert 'ESC_SIM_WWDT_BOOTRST_REQUESTED' in stderr,stderr
    print('PASS_G14_WWDT_OPT_IN_DEVICE_MODEL_ONLY_NOT_GUEST_INPUT_LOSS')

if __name__=="__main__":
    main()
