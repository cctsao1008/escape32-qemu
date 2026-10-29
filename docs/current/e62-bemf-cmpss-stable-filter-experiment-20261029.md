# E62 — First Sensorless BEMF Robustness Improvement (2026-10-29)

## Scope / immutable source boundaries

Status **SOURCE-BUILT EXPERIMENTAL; NOT Original Rel17.3; NOT production-ready.**

The 2026-10-29 perturbation screen `#40817417417` using the exact
three-instruction Original-derived experiment found 2/8 non-SHA
motor/observability passes and 6 failures without waived criteria:

| Analog condition | direct20 | second profile |
| --- | --- | --- |
| 2us PWM-correlated transient `0:16` | PASS | gentle FAIL (6 reversals) |
| relative positive phase sense offset `16:0` | FAIL (244 reversals) | steps FAIL (162) |
| relative negative phase sense offset `-16:0` | FAIL (245 reversals) | ramp100 FAIL (58, no closed loop) |
| combined `16:20` | PASS | ramp500 FAIL (3 reversals) |

The analog offset is a *phase sense-to-fixed DAC relative error*,
not measured board VBUS or nominal control reference. In the model
the stationary 1.65V phase sense baseline shifts by +/-16 ADC codes,
while CMPSS DAC remains 2048. This distorts the phase-crossing
timing and cannot be rigorously fixed by copying a filter setting.
These input/source and original-analyzer failures are retained.

## Isolated firmware change: stable CMPSS digital filter

Experimental source **branch**:
`cctsao1008/ESCape32@experiment/e62-bemf-stable-filter-20261029`,
pinned source commit `73f48f3b0c89a984d3f74177fd6342c84f5c7e95`.
Control/candidate are built from **the same source commit**, with
the same Motor Output=1, reference seed 2048, 3ms startup and
`ival/4` policy, MCU/SDK and SIM_ONLY board electrical profile.
The **only** candidate addition is
`AM13E_SIM_ONLY_BEMF_STABLE_FILTER=1` in
`e62_sim_only_early_bemf_stable_filter.cmake`.

Source `mcu/AM13E/hal/motor_bemf.c`:
- Default comparator filter stays at `samplePrescale=0`,
  `sampleWindow=5`, `threshold=3` in initialization, and
  `(existing speed-band prescale,5,3)` after native interval select.
- The explicit experiment replaces both with
  `DL_CMPSSLITE_configFilterHigh(cmp,31,25,20)`.
- On QEMU modeled 200MHz MCLK: `20*(31+1)*5ns = 3.2us`
  of stable comparator input required. Synthetic switching
  transient duration is independently set to 2us in the physical
  source model. The TI SDK permits a 24-bit sample prescale,
  window up to 64, and threshold > window/2. QEMU currently uses
  a **bounded delay approximation**, NOT full silicon filter samples.
- **Original ECAP1 capture, CAP1 ACK, TIMG12 commutation
  scheduler, timeout, fault latch, dead-time, OC/Trip, nFAULT,
  Guest CRC and DShot frequency remain unchanged.**
- The filter setting is NOT a board noise measurement and not
  a full equivalent of STM32 TIM2 input capture filtering.

## Controlled A/B and strict gates

Workflow:
`.github/workflows/e62-experiment-source-built-bemf-filter-ab.yml`

It builds 2 source ELFs for each of direct20 and gentle, verifies
exact source commit and pinned TI SDK SHA, uses exact original JSON
DShot scenarios from 1kHz external FC, and runs each in:

1. Default analog source (`nominal`).
2. Independent QEMU physical switching disturbance (`0:16`).

It saves 4 separate source Guest executions per profile (8 total),
including whole-window rotor/current events and independent
Original P1 analyzer **expected** SHA rejection. The unchanged
`tools/native_p1_qualification.py` must return code 1 and include
`ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN` for both source-built
ELFs. All **other** original strict conditions must pass for
control nominal, filtered nominal, and filtered noise. The
control/noise negative case is preserved with its actual failures;
the candidate must show *fewer* reversals and zero unwaived motor
failures, otherwise this experimental A/B job is RED. Additional
source-owned `E62_BEMF_STRESS_DIAG` events must prove that analog
noise was applied; these events are kept outside strict P1 event schema.

**No automatic pass from a green build.** No explicit transient
qualification means the experiment is inconclusive or fails.
An improved 2us noise test is NOT a solution to constant offset,
real board EMI, current sense, 47V/210KV propeller or formal P1.

## Next decision

1. If source-built filtered/noise results fail: compare the first
   `CMP_FILTER` transition, first genuine CAP1/ACK, TIMG12 and
   actual rotor torque reversal; do not adjust source model or P1
   thresholds until the failure is explained.
2. If the filtered/noise A/B passes: run the unchanged six-source
   nominal regression, then separately re-run all eight analog
   stress cases; offset tests are expected to remain open.
3. Evaluate board-calibrated VBUS/phase sense / DAC startup
   reference acquisition via the existing `AM13E_BOARD_SC5_CALIBRATION`
   design, and only then characterize real hardware. Do not
   hardcode new physical DAC codes without measured calibration.
