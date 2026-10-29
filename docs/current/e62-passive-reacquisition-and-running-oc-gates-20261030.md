# E62 — Passive Re-acquisition and Running OC Protection: Independent Gates

Date: 2026-10-30 (Asia/Taipei). Status: **EXPERIMENT_ONLY / NO HARDWARE QUALIFICATION**.

## Independent issue boundaries

| Issue | Implemented evidence | Not established |
| --- | --- | --- |
| [#5](https://github.com/cctsao1008/escape32-qemu/issues/5) | Source-owned coast BEMF quantization/phase permutation diagnostics, plus an isolated pure-C `ESCape32` passive observer | Board-calibrated rotor electrical angle/direction, actual ADC rate, safe windmill capture, starter/bridge enable |
| [#7](https://github.com/cctsao1008/escape32-qemu/issues/7) | Original no-WFI powered PA22 nFAULT and DShot WWDT loss PASS; separate neutral WFI/GDB OC-U/V/W PASS; new actual running-scenario current-sense overrange matrix in progress | True torque-generating phase overcurrent, real CMPSS thresholds/gain, hardware propagation delay, 47V/12S protection |

## #5: Passive phase acquisition contract

**Source:** [`motor_windmill_observer_plan.h/.c`](https://github.com/cctsao1008/ESCape32/tree/experiment/e62-bemf-stable-filter-20261029/mcu/AM13E/hal). This is a **standalone experimental pure-C observer** and is not integrated into the active ESCape32 startup loop.

Independent mandatory inputs:
1. A complete, coherent **three-phase ADC epoch**, unique/nonzero sample counter, acquisition/completion ticks and bounded age, with consistent uint32 wrapping clock and consecutive sample IDs.
2. Real actual **six PWM outputs inactive at capture**, no already latched OST/Trip fault.
3. Board-authenticated U/V/W phase route, ADC Vref and gain/offset/noise, actual timebase, inter-channel skew and sample-cadence specifications.
4. Code separation against a *measured board-specific minimum*, with all ADC codes bounded [0,4095].
5. Consecutive adjacent six-ranked-permutation transitions, with no skipped/reversed direction or stale timestamps; ≥3 is only an **experimental minimum candidate count**, not a rotor phase confidence bound or product requirement.

Return values are `REJECT`, `COLLECT`, or `CANDIDATE_ONLY`. The explicit function `am13e_windmill_motor_rearm_permitted()` **always returns 0**. No rotor angle is taken from QEMU and there is no direct PWM, DShot, timer or motor control call.

Host CI [#40917501312](https://github.com/cctsao1008/ESCape32/actions/runs/40917501312) first passed pure-C O2/UBSan. Added explicit six-output-inactive, fault-latch-clear and coherent-three-phase-epoch gates, then a required `max_sector_hold_ticks` to expire static phase ranks rather than inheriting stale rotor-motion confidence. **Final source CI [#40919333015](https://github.com/cctsao1008/ESCape32/actions/runs/40919333015) SUCCESS** on [commit `80121bd`](https://github.com/cctsao1008/ESCape32/commit/80121bd9585c6f3b85948eb8ae38f471ded8aa79), O2/-Werror + UBSan, all negative and positive tests. This proves only the pure-C defensive contract, not actual ADC/BEMF signals.

**Source-limited observability:** In 4 original native QEMU coast artifacts, terminal 100ms has **≤1 code** maximum phase contrast; 1kHz sampled debug trace shows **2 non-adjacent phase-rank transitions** during the earliest 100ms. A QEMU debug telemetry period is **not** the MCU ADC cadence. Real hardware current/bus/phase configuration and noise remain open.

## #7: Running current-sense OC source fault matrix

Three independent external source fixtures:
`scenarios/e62-native-p1-running-oc-{u,v,w}.json`; each is independently clocked by QEMU's **1kHz physical-FC frame timer** and is configured preboot, asserted at frame 2100 and released at frame 2300 during the approved positive DShot ramp.

**Experimental QEMU fault source:** one selected modeled current-sense amplifier ADC-like code is forced to **4095** at the native **analog input producer** while opt-in fault is active. This is NOT genuine motor-generated current. It never authors Guest CMPSS/TZ/IRQ/MCPWM registers or the physical motor equations. The real original Guest must react to its **original** comparator and OST3 route. The original P0 event enum and all P1 motor thresholds are unchanged.

Independent strict acceptance of each phase:
- full 3000 source-owned DShot frame continuity and actual powered `PWM_PAIR` before assertion;
- two authentic QEMU source diagnostic edges with exact frame/timestamp/channel identity and 4095 input code;
- simulated CMPSS threshold crossing → OST3 latch and real MCPWM fault IRQ pending **at assertion**;
- absolutely **no** source PWM commutation pair after the latched fault;
- OST3 latch persistent after analog fault release, **all six outputs inactive**, PWM carrier stopped at end, no automatic rearm;
- exact Original ELF SHA, no WFI/GDB, no Host Guest writes; explicit non-hardware/not-current provenance.

Workflow [#40918337864](https://github.com/cctsao1008/escape32-qemu/actions/runs/40918337864) is the strict independent source-built **three-phase OC-sense fault** experiment. A failure is not a reason to change the native P1 acceptance gate, fake a Trip or suppress output safety checks. Every artifact is preserved even on failure.

**Product-level OPEN:** Running current-sense overrange model PASS, if achieved, cannot qualify the actual physical motor current, shunt/amplifier gain and offset, MOSFET gate shutdown time or thermal/47V/propeller performance. Require schematic and electrical current/voltage limit provenance and scope-based bench evidence before adoption.

## Provenance policy

- Original Rel17.3 ELF SHA256: `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
- The source-built cold-sector candidate `step=0` remains **SIM_ONLY**, NOT a safe windmill restart in the 300ms coast failure.
- A true physical rotor-angle estimator or board-calibrated ADC observer has not been implemented.
- No software, QEMU or host PASS conveys `hardware_qualified=true`.
