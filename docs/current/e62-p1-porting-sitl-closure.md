# E62 — P1 Firmware Porting SITL Closure (2026-10-28)

## What P1 means in this document

This closes the **P1 Firmware Porting SITL** work proposed after the
P0 peripheral causality verification:

1. Original Guest DShot600 command-link **hard loss / timeout** with
   no Host firmware register writes, no WFI/GDB control and genuine
   Guest-owned WWDT feeds.
2. AM13E QEMU **peripheral negative/boundary contracts**: Timer, DMA,
   CMPSS/ECAP, Trip and WWDT.

This is **NOT** the independently failing **P1 Native Motor Dynamics**
strict startup benchmark. direct20 and steps remain **FAIL** and must
not be waived, repaired by model tuning or relabeled as a porting pass.

### Decision

**P1 Firmware Porting SITL named scenarios: COMPLETE — SIM_ONLY.**

**Overall Firmware Porting Signoff: NOT COMPLETE.**

**Board, UAV propulsion, safety and real motor load: NOT QUALIFIED.**

Unmodified Original ESCape32 Rel17.3 ELF SHA-256:

`05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`

## 1. Real no-WFI Original Guest input loss

Source-built GitHub Actions [#40639394403](https://github.com/cctsao1008/escape32-qemu/actions/runs/40639394403) **SUCCESS**.

The independently clocked external FC generated **2,800 physical-format
PA26 DShot600 frames** from cold boot through neutral, ramp and 20%
active hold. The source then stopped **before** the final programmed
neutral stage; no replacement neutral/command frame, Host Guest MMIO
write, fake watchdog feed or firmware patch was made.

QEMU captured **2,189 original Guest WWDT0 FEED writes**. After the
final Guest-owned FEED, the pre-existing hardware WWDT0 model expired
at the original **1,000,000,000 ns** virtual deadline with a **0 ns**
residual. The opt-in BOOTRST path logged

`ESC_SIM_WWDT_BOOTRST_REQUESTED: vns=3799067148`

with the source-owned **PB13 LOW; PWM frozen; resetcause=0x0e** behavior,
which the source QEMU implementation executes before requesting global
reset. This is a modelled output action, **not a probe of physical gate
voltage**.

The analyzer emitted:
`PASS_P1_NATIVE_GUEST_INPUT_LOSS_WWDT_BOOTRST_SIM_ONLY`, issues=[].

- Analyzer: `tools/native_p1_input_loss_audit.py`
- Independent No-WFI probe, opt-in stop: `tests/e62_autonomous_native_motor_probe.py --link-loss-last-frame 2800`
- Deterministic scenario: `scenarios/e62-native-p1-input-loss.json`
- Regression: `tests/test_native_p1_input_loss.py` (8 negative tests PASS)
- CI: `.github/workflows/e62-native-p1-input-loss.yml`

The Guest's source policy initializes WWDT0 when the receiver is
selected, then only accepted valid Core frames call
`DL_WWDT_restart()` (original pinned
`mcu/AM13E/hal/input_watchdog.c`). No SysTick/housekeeping feed is
substituted. Nominal QEMU LFCLK is **32768 Hz**; no hardware oscillator,
watchdog deviation, startup/restart timing or power stage qualification
is inferred.

## 2. Strict Peripheral Boundary Model

Source-built [#40639899206](https://github.com/cctsao1008/escape32-qemu/actions/runs/40639899206) **SUCCESS**.

| QTest | Negative/boundary checks | Recorded result |
|---|---|---|
| G6 | TIMG4/TIMG12 counter, one-shot ZERO IRQ/clear, peripheral reset and strict-model rejection | PASS |
| G7 | DMA0 Ch2 SRAM transfer, count/error/IRQ, invalid-source request and no fake capture | PASS |
| G10 | CMPSS0 / ECAP1 filter/route/Power/Reset, strict unmodeled access rejection | PASS |
| G13B2 | nFAULT/OC-U/V/W Trip latch, W1C only after physical fault release, read-only status | PASS |
| G5 | WWDT power/start/feed/expiry and invalid unmodeled policy | PASS |
| G14 | WWDT opt-in BOOTRST reset cause, PB13 low and PWM freeze | PASS |

These checks are **model-only QTest** tests, not running Guest firmware.
The independent *Guest-backed No-WFI* hard-DShot-loss result above is
what links actual source WWDT programming to this device contract.

## 3. Aggregate evidence

Six-source [Readiness Packet #40640025195](https://github.com/cctsao1008/escape32-qemu/actions/runs/40640025195)
**SUCCESS**, with P0 MMIO, P1 MMIO, DShot CRC, neutral nFAULT/OC,
in-flight nFAULT, and now original Guest no-WFI hard input loss.

Its status is `PASS_BOUNDED_SITL_PORTING_EVIDENCE_WITH_OPEN_ITEMS`.
The release-specific fields intentionally remain:

- `porting_complete = false`
- `hardware_qualified = false`
- `motor_p1_all_cases_qualified = false`

## 4. Not waived or qualified

- Physical AM13E LFCLK tolerance, actual WWDT BOOTRST timing and
  physical PB13/Gate/MOSFET output.
- Automatic post-reset arming and actual flight recovery. The P1 loss
  test demonstrates **reset request and model safe-off**, not full
  powered-on recovery, nor a board-level stop-time guarantee.
- Real analog CMPSS/ECAP thresholds, ADC board channels and
  power-stage overcurrent protection under physical voltage/temperature.
- The uncalibrated ECX87 rotor/propeller model, 47V/210KV customer
  configuration and **P1 Motor Dynamics direct20/steps reversal FAIL**.
- L1 firmware release candidate gate and actual hardware bring-up
  signoff are independent next steps.

This bounded P1 SITL closure **does not require changing Original Guest
code, motor inertia/load, capture threshold, comparator BEMF data or
the unchanged strict rotor acceptance rules**.
