# E62 BEMF Robustness Matrix — SIM_ONLY Research Gate (2026-10-29)

## Decision, provenance and immutable gates

Status: **EXPERIMENTAL, NOT Original Rel17.3 P1 and NOT hardware qualification**.

The original Guest ELF SHA256 stays `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
The only accepted Guest for this research matrix is the previously measured exact
three-instruction `3ms + ival/4` **NON-ORIGINAL** ELF SHA256
`0975dd2169b308e1b4a3d131078f744ab6c0f6efa6acc65c7953d2a5f9ecfcd5`.

Do not modify `native_p1_qualification.py`, six existing DShot JSON fixtures,
original P0/P1 thresholds, overcurrent/Trip/nFAULT/dead-band enforcement,
W1C evidence, timeout/failed-zero-cross recovery, Guest CAP1 or TIMG12.
No Guest SRAM/MMIO writes or synthetic crossing/capture injection. No
Original P1 PASS claim for an experimental SHA. Existing six scenarios
[#40811933252](https://github.com/cctsao1008/escape32-qemu/actions/runs/40811933252)
are the already established **unchallenged** six-scenario diagnostic baseline.

## Source-grounded engineering rationale

- **NXP/Freescale AN1914** (uploaded Rev.1, 2005), §5.4.3
  *Starting (Back-EMF Acquisition)* and motor-kit startup constants on
  PDF pp. 25–27 and 51–52. Startup first needs sufficient BEMF; acquisition
  before reliable running handoff and startup blanking are distinct.
  This is NOT a license to copy the document's motor-specific timing
  parameters or change existing E62 startup guards.
- **Microchip AN1160 Rev.D** (uploaded DS00001160D, 2022), PDF pp. 8–10,
  *Back-EMF Sampling* and *Digital Filter (Majority Function)*:
  PWM switching/ringing can create false zero-crossing transitions.
  Its dsPIC ADC majority-function implementation is a reference concept,
  **NOT** evidence that the original AM13E CMPSS/ECAP firmware implements
  the same digital filter or should be ported.
- **ST AN1946 Rev.2** (uploaded ST7MC application note), PDF
  pp. 6–8, 11–13, 29–33: PWM ON/OFF sampling tradeoffs, virtual neutral,
  low-speed / low-voltage BEMF detection sensitivity.
  The present model's 2048 code is a modeled 1.65V midpoint,
  **not** a real board DAC or electrical calibration.

These references motivate **testing**, not acceptance thresholds or
new firmware control logic.

## Physical-source model: opt-in, bounded, off by default

New QEMU machine-only property:
`esc-sim-bemf-robustness=OFFSET:SWITCH_CODE` with
`-24 <= OFFSET <= 24` integer ADC codes and
`0 <= SWITCH_CODE <= 32` integer ADC codes.
`off` is the default; the setting is rejected if both are zero.
One 12-bit code is ~0.806mV on **this 3.3V/4095 simulation scale**,
not a board-characterized noise amplitude.

1. Keep native current/rotor/Energy solver and physical PWM AQ/DB source
   exactly as before.
2. Generate genuine rotor-derived sinusoidal phase BEMF, convert through
   the original `1.65 + 0.02*BEMF` model.
3. Apply signed `OFFSET` to the BEMF *sense code* at the immediate
   QEMU analog frontend, **before** existing CMPSS evaluation;
   this models a **relative analog sense-to-DAC bias**, not a change
   to the Guest's configured DAC reference, and not a new board profile.
4. For `SWITCH_CODE > 0`, apply a deterministic bounded signed
   transient for 2us after **actual clocked MCPWM six-pad mask changes**.
   Alternation is reproducible; no artificial zero-cross event is
   inserted. A stress log `BEMF_STRESS` records original code,
   perturbed code, signed offset, applied spike and switch count.
5. Any 12-bit overflow is fail-closed; never clip it to a plausible
   sensor code. OC, nFAULT, gate readiness and fault latch are untouched.

This is an **electrical signal susceptibility screening**, not a
verified model of real GaN/Si switching EMI, VBUS ripple, dead-time
distortion, propagation delay or PCB analog wiring. In particular,
a successful noise run cannot certify hardware immunity.

## Eight experimental stress cases, existing immutable scenarios

CI: [E62 BEMF analog robustness workflow](https://github.com/cctsao1008/escape32-qemu/actions/workflows/e62-experiment-bemf-robustness-matrix.yml).

| Pair | Stress code | Cases | Question |
| --- | --- | --- | --- |
| Switching transient | `0:16` | direct20, gentle | Can PWM-correlated disturbances trigger incorrect early CMPSS/CAP1? |
| Positive analog bias | `16:0` | direct20, steps | Is startup sensing sensitive to measured phase/reference mismatch? |
| Negative analog bias | `-16:0` | direct20, ramp20_100ms | Is offset direction asymmetric? |
| Combined stress | `16:20` | direct20, ramp20_500ms | Does combined offset and switching disturbance defeat capture stability? |

Additional control: the separate existing six-scenario workflow
must rerun **with opt-in off**, after any QEMU analog source change.
These eight experimental stress cases supplement, NEVER replace, those
original scenarios. The `steps` input tests staged demand; it is **NOT**
proof of a standalone stop/rearm/restart protocol.

## Strict experimental acceptance and evidence

Every case:
- Exact pinned candidate and original SHA, signed three-instruction proof,
  unchanged original scenario JSON digest, independent 1kHz FC source.
- Actual physical BEMF perturbation must be present in `BEMF_STRESS`
  logs; when `SWITCH_CODE > 0`, at least one nonzero *source-owned*
  switch artifact is mandatory. If not observed, **FAIL**, not a
  successful noise-tolerance measurement.
- Run the **unchanged** strict Original P1 analyzer. It MUST reject
  the non-original Guest with `ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN`.
  Every *other* unwaived motor/observability P1 failure must be absent.
- Require zero significant rotor direction changes, positive-only
  powered RPM sign over 50 RPM, and minimum 12 each genuine Guest
  closed-loop PWM pairs, ECAP1 W1C ACK, TIMG12 W1C ACK.
- Missing observation, probe crash, invalid physical source or
  any non-SHA gate failure makes the experimental CI red. All raw
  `.p0.events.log`, `.qemu.log`, evidence JSON, original-gate
  negative verdict JSON and configuration/provenance are retained.
- Even green means **stress-screened SIM_ONLY diagnostic**, NOT P1,
  NOT false-zero-cross immunity certification, NOT motor hardware PASS.

**Open after initial eight cases:** targeted low-speed CAP1 temporal
consistency, restart/re-acquisition from a genuine second demand
interval, back-EMF comparator/DAC calibration from PCB measurements,
load/propeller inertia sweeps, voltage and temperature corners,
separate OC/nFAULT injected fault tests, and actual phase-current/torque
ripple. Do not redefine an initial negative result as success.

## Prior motor-output fail-closed RCA (separate)

[CI #40812856179](https://github.com/cctsao1008/escape32-qemu/actions/runs/40812856179)
finished PASS with source-built Motor Output=1:
`no_seed` => `motor_output_start_reject=3`,
`runtime_fault_reason=6`, `fault_latched=1`;
`2048` modeled seed => `reject=0`, `fault=0`, `latched=0`.
This is a verified **SIM_ONLY reference-readiness causal branch**,
not authorization to hardcode 2048 into production firmware.
