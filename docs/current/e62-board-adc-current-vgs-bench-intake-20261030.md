# E62 — Actual Board ADC, Current-Sense and Six-Vgs Trace Intake

Date: 2026-10-30. Owners: **EE/board bring-up + SW validation**, actual signoff TBD.
Status: **NO PHYSICAL E62 BENCH DATA CAPTURED**. This document is a
capture/readiness protocol, not an approval or a virtual PCB specification.

## Why separate three physical evidence classes?

1. **#5 AM13E ADC passive phase sampling:** `analog_runtime.c` has an
   actual nine-code `AM13E_AdcRaw` snapshot. It uses **software-triggered
   three-ADC sequencers, 640-cycle sample windows, ADC0/1/2 INT1 EOC**
   and only publishes after all three complete. It is a **PendSV
   housekeeping scan**, not a PWM-synchronized rotor phase estimator.
   A coherent published snapshot proves software ownership/completion
   but does NOT prove actual simultaneous phase sampling or three-phase
   inter-channel timing, valid board phase route, or rotor direction.
2. **#7 actual phase-current transfer:** QEMU's ADC-like OC source
   `1000+4*abs(Iphase)` and opt-in overrange code 4095 are SIM_ONLY.
   Never adopt those as actual shunt/amplifier gain, offset or current
   threshold. Real board source MUST establish U/V/W current-sense
   transfer from an **independent calibrated current reference**.
3. **#7 physical power-gate shutdown:** The simulated CMPSS1/2/3
   → Trip3/OST3 → six-pad-off PASS validates only modeled functionality.
   Real MOSFET/GaN **Vgs** and driver fault source require actual rated,
   electrically appropriate differential scope measurements and
   independently reviewed safety limits. Neither MCU pad nor a QEMU
   output is automatically a device Vgs measurement.

## Hardware-first preflight — stay at H0/H1

Do not conduct any powered high-current/propeller tests from this
document alone. Before H1, EE must document board serial/revision and
power-stage topology (six independent gates vs PWM-enable), exact
U/V/W phase-to-pin mapping, ADC channel mux and reference, shunt and
amplifier transfer, MOSFET/GaN and gate-driver limits, nFAULT polarity,
Trip3 routing and actual gate-driver enable state. Confirm an approved
current-limited, low-energy, mechanically guarded test setup with
**no exposed propeller** and electrically appropriate probes.

The pin-map/ADC-cadence and acceptable gate-off latency are currently
**TBD**, not the QEMU default or values from an unrelated board.
If board support lacks a genuine source signal or any of six Vgs probes,
the corresponding measurement stays **OPEN** rather than silently
filling its column with a simulated value.

## #5 actual ADC complete-epoch capture

Archive a raw CSV with the **exact** column order:

```csv
sample_count,acquisition_tick,completion_tick,read_tick,phase_a,phase_b,phase_c,adc0_eoc,adc1_eoc,adc2_eoc,snapshot_coherent,six_gate_off,trip_clear,trigger_overruns
```

- Counters/ticks are unsigned native firmware values (do not convert
  to floating-point time before exporting); `phase_a/b/c` are raw
  **12-bit ADC codes**, not fake/estimated rotor theta.
- Source instrumentation must show all three ADC EOC completion flags,
  atomic published snapshot, actual six-output **inactive** at the
  observation moment, existing Trip not latched, and monotonic
  trigger-overrun counter.
- Declare the real source tick clock in `tick_hz` (cannot be inferred
  from the QEMU 1kHz diagnostic), and **board-justified** budgets
  `max_scan_ticks`, `max_gap_ticks`, `max_age_ticks`,
  `max_rank_hold_ticks`, `min_adjacent_codes`.
  A confidence candidate from this intake is still NOT a rotor angle.
- Capture the neutral-to-coast period and separate controlled
  directions **only after** the board is electrically and mechanically
  cleared. The ADC CSV alone does not prove intra-scan inter-channel
  skew; separate timer/trigger measurements are needed.

Required JSON manifest fields (`schema=e62.bench.adc-epoch.v1`,
`capture_kind=BENCH_CAPTURE_DECLARED_UNVERIFIED`):
`board_revision`, `board_serial`, `firmware_commit` (40-hex Git SHA),
`instrument_id`, `measured_at_utc`, `trace_sha256`,
`phase_pinmap_ref`, `adc_calibration_ref`, `sample_clock_ref` and
all six explicit numeric timing/contrast limits above.

Run:
```sh
python3 tools/e62_board_adc_epoch_intake.py \
  --csv <REAL_ADC_EXPORT.csv> \
  --manifest <REAL_ADC_EXPORT.manifest.json> \
  --output artifacts/e62-board-adc-epoch-intake.json
```
The tool will reject missing/duplicated samples, stale/invalid
acquisition, EOC/coherence flags, gate-on, unacknowledged fault,
insufficient phase code contrast, skipped phase rank and forged
`qemu:` provenance prefixes. Its verdict **never permits motor rearm**.

## #7 independent U/V/W current transfer

Archive one CSV:
```csv
phase,point_id,reference_current_ma,adc_raw_code
```

The three phase groups must each include independently referenced
zero, **both** signed current polarities and at least seven readings
with five distinct excitation currents; clipping at ADC code 0/4095
is explicitly rejected. A bench topology manifest **must explicitly
select** `SIGNED_LINEAR` or `ABSOLUTE_LINEAR`, not assume the QEMU
absolute-current response. Sign/polarity, common-mode behavior,
reference Vref, shunt, phase mux and amplifier are EE responsibilities.

Manifest: `schema=e62.bench.current-transfer.v1`,
`capture_kind=BENCH_INDEPENDENT_CURRENT_REFERENCE_UNVERIFIED`,
`hardware_excitation_method=LOW_ENERGY_NO_PROPELLER`, plus
`board_revision`, `board_serial`, `firmware_commit`,
`measured_at_utc`, `reference_instrument_id`, `adc_instrument_id`,
`raw_trace_sha256`, `current_probe_cal_ref`,
`adc_reference_cal_ref`, `shunt_amplifier_schematic_ref`,
`adc_phase_route_ref`, and `transfer_topology`.

```sh
python3 tools/e62_board_current_transfer_intake.py \
  --csv <REAL_CURRENT_SWEEP.csv> \
  --manifest <REAL_CURRENT_SWEEP.manifest.json> \
  --output artifacts/e62-board-current-candidates.json
```

Only **candidate** per-phase gain (ADC codes/A), ADC zero offset and
RMS/max residual are computed. This does NOT provide an approved
CMPSS DAC trip-current equation: actual comparator reference, DAC
transfer/polarity, current signal bandwidth, gain temperature drift
and EE-approved quantitative thresholds still require verification.
No Firmware calibration macro or DAC register is written.

## #7 oscilloscope fault-to-six-Vgs shutdown

Archive one **scope-digitized** CSV with the exact columns:

```csv
time_ns,fault_active,u_h,u_l,v_h,v_l,w_h,w_l
```

`fault_active` and all six Vgs activity discriminator columns must
be exact **0/1** from an externally documented threshold, referencing
the *actual six device Gate-to-Source* signals, not raw MCPWM pins.
Retain the underlying analog scope capture: this CSV is only a
derived audit aid. Record actual instrument probe attenuation,
reference, isolation limits, fault assert/release polarity, DUT,
firmware Git SHA, and raw SHA-256.

Run separately for `nfault`, `oc_u`, `oc_v`, `oc_w`, **only**
under EE-approved safe H1 conditions, not under unguarded prop load.

Manifest: `schema=e62.bench.six-gate-fault.v1`,
`capture_kind=BENCH_VGS_SCOPE_DIGITALIZED_UNVERIFIED`,
`fault_source`, `board_revision`, `board_serial`,
`firmware_commit`, `instrument_id`, `measured_at_utc`,
`raw_trace_sha256`, `gate_probe_reference`,
`fault_probe_reference`, `gate_discriminator_ref`,
`fault_polarity_ref`, `max_sample_gap_ns`,
`min_pre_fault_ns`, `min_post_release_ns`,
`approved_max_gate_off_ns` (**null if not formally approved**).

```sh
python3 tools/e62_board_gate_fault_intake.py \
  --csv <REAL_VGS_FAULT_CAPTURE.csv> \
  --manifest <REAL_VGS_FAULT_CAPTURE.manifest.json> \
  --output artifacts/e62-board-six-gate-fault-intake.json
```

The tool computes a **conservative two-edge latency interval**.
The upper bound uses the last fault-inactive sample before assertion
to the first stable six-off sample. The lower bound uses the last
still-gate-active sample relative to the first fault-active sample
(clipped at zero). This accounts for both unobserved transitions
**between scope samples**; simply subtracting the two sampled
transition times can underestimate fault-to-off delay.
If an approved numeric limit falls between the bounds, the result is
`TIMING_INDETERMINATE_AT_SAMPLE_RESOLUTION`, not PASS or FAIL.

The result is not a proven silicon propagation-delay specification. It rejects an unobserved fault edge,
missing release, missing pre-fault active Gate, incomplete six-device
capture, gaps, late gate activity, or fewer than three stable off
samples. Captured no-rearm is **only within the recorded trace**;
an actual persistent OST latch still needs independently correlated
MCU readback/physical debug evidence. Numeric gate-off acceptance
is **OPEN** without an independently approved limit.

## Provenance, integration and signoff

For all three CLI utilities, calculate raw `trace_sha256` or
`raw_trace_sha256` from original captured CSV bytes, and preserve the
unchanged instrument waveform export plus signed lab report. These
self-declared manifests and hashes detect file modification but **cannot
authenticate the instrument or prove the capture was physically taken**.

All current sample files in CI are **synthetic negative-control unit
fixtures only**, never board data. The original
`docs/fixtures/e62-hardware-measurements.csv` stays blank and
`OPEN_NO_BOARD_MEASUREMENTS` until genuine bench data arrive. No
automatic PASS is inferred from parsing a trace. A human EE/SW
review must link each capture to physical pin/polarity, instrument
calibration, firmware and component operating limits and update the
original hardware matrix only after independent acceptance.

### Specific decision gates before closing issues

- **#5:** actual verified ADC phase routing, conversion time/cadence
  and inter-channel skew; noise/freshness/phase-order confidence over
  CW+CCW/coast/restart, plus a *separate* safe, bounded arbitration
  and motor rearm policy (currently **intentionally disabled**).
- **#7:** real current amp gain/offset/polarity and independently
  approved current-OCP DAC threshold; scope-based nFAULT/OC U/V/W
  device Vgs six-off latency and retained latch; under/over-voltage,
  thermal and WWDT hardware reset/waveforms. True motor load testing
  requires separate guarded approval and customer current-definition
  alignment.

**No bench-captured data, physical phase calibration, physical
overcurrent, 47V/12S or true gate-off timing is claimed here.**
