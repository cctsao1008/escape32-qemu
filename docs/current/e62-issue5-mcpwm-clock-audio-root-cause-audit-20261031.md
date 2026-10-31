# E62 #5 — Source-backed Audio Timeline and MCPWM Clock Root-Cause Audit

**Date: 2026-10-31 | SIM_ONLY | immutable ESCape32 Original Rel17.3 | unchanged Original P1 | no product/hardware qualification**

## Confirmed: boot audio does not overlap either 20% demand

The original `am13e-port-v2` firmware runs startup music with the motor MCPWM output, not an independent buzzer. The shared Motor/Audio backend uses the same physical motor pads; it requires exclusive ownership and restores inactive DRIVE staging when the sound finishes.

A QEMU *hardware-register* observer was added on the prior `experiment/e62-apc24x12e-47v-coast-20261031` branch, commit `ed833b569`:
- `PWM_TBCTL`: actual Guest MCPWM counter-mode / divider writes
- `PWM_AUDIO_PERIOD`: period changes while the PWM divider is /32 (source evidence consistent with motor sound)
- `tools/e62_audio_motor_timeline.py`: compares real DShot stages, source PWM pair masks and model rotor RPM

**Source-backed outcomes:** CI [#41178267331](https://github.com/cctsao1008/escape32-qemu/actions/runs/41178267331) for 24V and [#41178267276](https://github.com/cctsao1008/escape32-qemu/actions/runs/41178267276) for 47V. Original firmware SHA-256 `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`; each original DShot600 source scenario 5,100 frames (neutral 1500 / positive 1500 / coast 300 / positive 1500 / neutral 300). No Guest control register injection, WFI breakpoint, fake CAP1 or source trace waiver.

| SIM_ONLY model | /32 clock writes before first positive | Note-period writes before first positive | Audio clock candidates inside *either* positive | 6-step digital nonadjacent transitions in positives | Strict Original P1 |
|---|---:|---:|---:|---:|---|
| KV147 24V no prop | 16 | 5 | **0** | 0 | **FAIL** |
| KV210 24V no prop | 16 | 5 | **0** | 0 | **FAIL** |
| KV210 47V no prop | 16 | 5 | **0** | 0 | **FAIL** |
| KV210 47V APC J1 | 16 | 5 | **0** | 0 | **FAIL** |
| KV210 47V APC J2 | 16 | 5 | **0** | 0 | **FAIL** |
| KV210 47V APC J5 | 16 | 5 | **0** | 0 | **FAIL** |

All fail unchanged `STARTUP_SIGNIFICANT_DIRECTION_REVERSAL` during both commanded-positive segments. Recorded digital `PWM_PAIR` sequence is `8 -> 2 -> 3 -> 6 -> 4 -> 7 -> 8` (source-mask order is consistent, but this is not a calibrated physical wiring/torque-polarity proof).

For **KV210 24 V**, exact previous run register timestamps:
- 11.370 ms: first source `TBCTL` /32 (music-related hardware clock candidate)
- 11.405 ms, 136.430 ms, 261.430 ms: startup song period updates
- 386.427 ms: restore /2 after initial song
- 637.069 ms: another /32 audio-clock candidate (post-arm indication)
- 637.104 ms, 762.117 ms: note period changes
- 887.114 ms: restore /2 after second sound
- **1500.026 ms: first positive DShot** (approx. 613 ms after last observed audio clock exit)
- **3300.026 ms: second positive DShot**; **no /32 or audio-period writes** in either positive segment

These are QEMU hardware register timestamps, not direct reads of private firmware `audio_owner`. It is highly unsupported to claim that active boot music is causing the *continuous* positive-demand rotor oscillation; a residual initial-condition impact cannot be wholly excluded.

## Distinct source-backed QEMU clock model defect

The QEMU native machine source at `machine/am13e23019.c` defines the MCPWM clock source as **100,000,000 Hz**, and `am13e_pwm4_hz()` divides this by the Guest's `TBCTL.CLKDIV` selection. That historical simulator constant is correct as a **legacy baseline reference**, but inconsistent with the **actual Guest model timing intent**:

- `ESCape32/mcu/AM13E/hal/motor_safety.c` states `MCPWMCLK=MCLK200MHz`, configuring DRIVE `DL_MCPWM_CLOCK_DIVIDER_2` and computing PWM carrier periods from `AM13E_APP_MCLK_HZ/2`.
- `motor_audio_plan.c` computes note pitch from `200 MHz / 32 = 6.25 MHz`.
- TI AM13E SDK `mcpwm_basic_pwm_generation` example explicitly provides MCPWM TBCLK=200MHz and a 19999 period for 10kHz: https://software-dl.ti.com/mcu-sdk/esd/AM13E2X-SDK/26_01_00_03/exports/docs/docs/am13e230x/user_guide/chapters/examples/am13e230x/generated_files/mcpwm_basic_pwm_generation/README.html

The old QEMU trace **measures**:
- /32 music-timebase at **3.125 MHz**, rather than the firmware's intended **6.25 MHz**;
- /2 motor-drive timebase at **50 MHz**, rather than **100 MHz**.

A period chosen by the 200MHz-based firmware can therefore result in about **half the PWM frequency** under the historical QEMU model. This is a measurable source-clock model mismatch; it is **not proof by itself** that the recorded reversals have this sole cause.

**Important:** QEMU `AM13E_SIM_TIMER_HZ = 100MHz` for the *separate* TIMG4/TIMG12 timer domain is not being modified by this MCPWM experiment. Do not double every peripheral clock globally.

## Safe A/B correction / source provenance contract

This independent branch `experiment/e62-mcpwm-200mhz-source-clock-20261031` adds a **new default-off QEMU machine property**:
`esc-sim-mcpwm-root-200mhz=on`

- Without opt-in, historical QEMU source clock stays **100 MHz**, preserving existing test baselines.
- With opt-in, only the **MCPWM source clock** becomes **200 MHz**; each Guest-written /2 or /32 divider remains unchanged.
- QEMU PWM historical read-only observer offset `0x44` exposes **effective root-clock Hz**, verified by the host runner and CI against the explicit machine property. Mode events show actual measured divider/period.
- Versioned control contract: `configs/e62-mcpwm-clock-control-v1.json` with motor KV210 24V and KV210 47V no-prop; all other parameters, Original ELF, 5,100 DShot frames, initial rotor angle -30°, and strict Original P1 remain unchanged.
- Separate source-built [MCLK200 Original Guest CI workflow](https://github.com/cctsao1008/escape32-qemu/actions/workflows/e62-mcpwm-200mhz-audit.yml) must produce **actual readback, complete source trace, unchanged strict Original P1 verdict and raw artifacts**. If significant reversal persists the job must remain FAIL.
- A green host test or a correct clock readback alone is **not** motor restart PASS or hardware signoff.

## Next causal analysis if source-clock A/B still fails P1

Inspect genuine `PWM_PAIR`, model current/rotor torque, selected floating-phase voltage and `CMP_FILTER -> CAP1 -> TIMG12 -> PWM_PAIR` event times under both clocks. Correct only physically demonstrable QEMU inaccuracies; do not modify ESCape32 Firmware or relax Original P1 for simulation compatibility.

**Issue #5 remains OPEN; Issue #7 remains unchanged.**
