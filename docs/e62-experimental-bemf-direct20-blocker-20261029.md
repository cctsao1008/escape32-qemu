# E62 Direct20 early-BEMF A/B: why the current experiment is NOT valid
Date: 2026-10-29 (Asia/Taipei)

## Evidence, no P1 qualification

- Original pinned REL17.3 ELF SHA256:
  `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`
  remains **unchanged**. This document covers distinct, separately
  recompiled, experimental ELF builds only.
- Both experimental Guest ELF builds use the same SIM_ONLY board compile
  profile with **uncalibrated** motor-output, dead-time, nFAULT and OC
  DAC codes. This is an exploratory fixture, NOT actual board safety.
- [A/B run #40724929982](https://github.com/cctsao1008/escape32-qemu/actions/runs/40724929982)
  compiled QEMU and both experimental firmware images.
- Control case: source log
  `e62-exp-control.qemu.log` in workflow artifact
  `e62-early-cap1-direct20-exp-not-original-guest`,
  artifact ID 12832263265.

### Grounded control source observations

| Event | Count | First / last time |
|---|---:|---|
| External FC DSHOT | 3300 | 0.000100–3299.010100 ms (QEMU virtual) |
| First positive 20% DShot | 1 onset | 1500.000100 ms |
| WWDT_FEED | 1430 | last **1500.044 ms** |
| PWM_PAIR | 1 | 18.235 ms (before positive command) |
| SWITCH | 144 | last 136.459 ms (before positive command) |
| ROTOR / ENERGY / BEMF_FRONTEND | 3281 each | 19.235–3299.236 ms |
| CAP1 | **0** | None |
| TIMG12 | **0** | None |
| ROTOR mechanical rpm | **0** | Remains zero for the whole logged trajectory |

Positive command arrival is followed almost immediately by a lack of
further original-Guest watchdog feed. This is **consistent with** a
fault/reset/halt/spin or other blocked firmware execution path; its
precise CPU PC and fault reason are **not established** by this trace.
The motor current model still produces neutral-stage carrier artifacts,
but this is NOT proof of positive-throttle gate authorization.

A prior run without explicit SIM_ONLY board output definitions
[#40721415949](https://github.com/cctsao1008/escape32-qemu/actions/runs/40721415949)
had zero `PWM_PAIR`, `ROTOR` and `CAP1`: the safe Reference board
compiled with `AM13E_MOTOR_OUTPUT_CONFIGURED=0`. This failed
control prerequisite; after adding explicit fixture definitions,
the control produced physical motor-model source events, but stalled
on positive DShot.

## Why not simply add more OC/PWM constants

The original firmware has fail-closed explicit electrical contracts:
`mcu/AM13E/hal/motor_output_configuration.h` requires complete
gate/pad, RED/FED and reset-inactive definitions;
`motor_fault_route.c` requires complete three-phase independent
OC DAC codes/polarities when outputs are enabled. Inventing physical
hardware values is **not** an acceptable product fix.

The experiment currently uses explicit QEMU-only OC DAC midpoint
2048 (not calibrated in amps). It must **not** be merged into
production board configuration, nor used to waive strict original
motor P1 acceptance.

## Next controlled diagnostic

Before comparing 10ms versus 4ms initial CAP1 acceptance:
1. Observe (read-only) the experimental Guest PC, original symbols,
   IRQ/fault cause, GPIO PB13/PA22 and OST2/OST3 state at first
   positive DShot. Do not write Guest SRAM or fabricate a CAP1.
2. Establish that a recompiled 10ms-policy **control** passes
   all preconditions: positive-throttle powered PWM_PAIR, moving ROTOR,
   accepted CAP1, Guest-owned TIMG12. The source state must match
   the still-unchanged pinned original route under an explicitly
   documented simulation-only board model.
3. Only then run the identically built 4ms candidate and compare
   source CAP1 acceptance, first TIMG12 and actual rotor reversals.
4. Keep both strict Original REL17.3 P0/P1 gates red/open when they
   fail; do not claim QEMU-only A/B as hardware qualification.

## Current verdict

**A/B INVALID / BLOCKED BY RECOMPILED-GUEST STARTUP FAULT.
No conclusion on 4ms BEMF acceptance. Motor P1 remains FAIL / OPEN.**
