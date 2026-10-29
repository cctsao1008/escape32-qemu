# E62 H0/H1 bench ADC epoch and six-Vgs fault measurement gates

2026-10-30. **Protocol only. No E62 physical capture exists; no hardware PASS.**
Applies to [Issue #5](https://github.com/cctsao1008/escape32-qemu/issues/5)
and [Issue #7](https://github.com/cctsao1008/escape32-qemu/issues/7).
Use with [intake schemas](e62-board-adc-current-vgs-bench-intake-20261030.md).
This is an EE-approved laboratory measurement preparation document,
not an authorization to energize a power stage.

## H0 — Unpowered electrical/provenance readiness (STOP before H1 if incomplete)

1. Record the actual E62 board revision, serial, gate driver, MOSFET/GaN
   topology, supply/ground isolation, schematic revision, probe voltage
   ratings and independently approved lab risk controls. No propeller.
2. EE maps ADC0/1/2 sequencers and true U/V/W phase input nets,
   amplifier/voltage dividers, Vref and ADC 12-bit saturation behavior.
   Export the **native** sample counter, acquisition/completion/read
   ticks, three EOC flags, coherent published snapshot, overrun counter,
   six-gate-inactive state and OST/Trip-clear observation. Do not
   substitute QEMU registers, debug telemetry 1kHz or inferred ADC time.
3. For each ADC channel measure trigger-to-sample aperture,
   sample-to-EOC timing and inter-channel start/hold skew with independent
   timing strobes or an instrument-correlated record. The firmware's
   640-cycle sample window alone does not specify the complete physical
   conversion or timestamp capture uncertainty. Note tick source and
   actual tick rate `tick_hz`; verify unsigned 32-bit wrap assumptions.
4. Under approved **non-driving low-energy excitation** (bridge
   disabled), inject documented, phase-labelled calibrated signals
   if authorized. Record ADC raw-code offset, noise, separation
   (`min_adjacent_codes`), and scan/read jitter. This does not qualify
   a rotating motor, BEMF electrical angle, direction or rearm.
5. Approve provenance and bounded `max_scan_ticks`,
   `max_age_ticks`, `max_gap_ticks`, `max_rank_hold_ticks` based on
   instrument resolution, firmware ordering and actual clock. Collect
   original raw exports; hash each original CSV (SHA-256) before analysis.
   The intake now explicitly rejects overlapping/reordered epoch reads.

## H1 — Guarded low-energy real board observation (EE authorization required)

**ADC / Issue #5:** after H0 signoff, measure *passively* rotating
motor BEMF with gate drive disabled and no propeller. Capture actual
phase-net probe traces U/V/W, mechanical reference direction (external
encoder or equivalent separately verified reference), MCU sampling
strobes and the raw ADC epoch stream on a shared timebase. Required
states: stationary, CW coast, CCW coast, low-speed/noisy near-stall,
1500/3000ms coast/restart context and a separate 300ms negative case.
Do not perform an energized restart or claim rotor angle from the
phase-rank CSV. Compare physical phase order to U/V/W pinmap and
annotate any <1-LSB/noisy or nonadjacent rank events. Every
hardware-based rearm decision remains blocked pending separate policy.

**Fault / Issue #7:** to capture one assertion and one release while
observing all six *actual FET Gate-to-Source* waveforms, provide
**at least seven simultaneous, electrically suitable oscilloscope
channels**: CH1–CH6 = U_H, U_L, V_H, V_L, W_H, W_L differential Vgs;
CH7 = independently probed fault source (nFAULT/OC-U/OC-V/OC-W,
one scenario per capture). Recommended CH8 = driver enable or
physical trip/OST indication where accessible; internal latch status
must be separately correlated by timestamped readback. If the
available instrument has fewer channels, use externally synchronized
acquisitions **only after measured trigger/clock skew has been
documented**, or leave the seven-channel safety timing **OPEN**.
Never combine unrelated shots as if simultaneous.

Before test, document every channel's gain, attenuation, bandwidth,
ground-reference/isolation, deskew, discriminator threshold and
active polarity. The CSV 0/1 gate activities are derived from and
**must not replace** stored analog waveforms. EE must approve
current-limited, mechanically guarded injection and independent
fault source wiring. First capture nFAULT, then separately OC-U/V/W.
Do not infer actual overcurrent from the SIM_ONLY 4095 ADC source.
Retain the original analog traces and board firmware Git SHA.

Let `F0` = last sampled fault-inactive time, `F1` = first
fault-active time, `G1` = first **sustained** all-six-off sample,
and `G0` = last measured gate-active sample at/after `F1` before
`G1` (if observed). A conservative digitized bound is:

```text
T_fault_to_safe_off_upper_ns = G1 - F0
T_fault_to_safe_off_lower_ns = max(0, G0 - F1) if G0 observed, else 0
```

The underlying real transitions occur between sample edges.
Reject a reactivation after a sustained three-sample all-off window,
even when the scope capture later ends all-off. Require at least
three all-off samples **while fault asserted** and three after
release, plus uninterrupted sample coverage. Three is only a
digital trace audit heuristic, not a qualified hardware time limit.
Classify against an independently approved numeric limit only:
upper ≤ limit → `CAPTURED_TIMING_UPPER_BOUND_WITHIN_DECLARED_LIMIT`;
lower > limit → `CAPTURED_TIMING_LOWER_BOUND_EXCEEDS_DECLARED_LIMIT`;
otherwise → `TIMING_INDETERMINATE_AT_SAMPLE_RESOLUTION`.
None conveys hardware PASS, OST silicon latch qualification, or
rearm permission without EE evidence review.

## Open evidence and stop conditions

- **#5 OPEN**: genuine ADC exporter, sampled physical channel timing
  and skew, pinmap/calibration, independently measured rotor direction,
  low-speed confidence and safe windmill recovery policy.
- **#7 OPEN**: physical current amplifier and comparator/DAC transfer
  calibration; six simultaneous Vgs + fault scope captures; approved
  shutdown latency, retained latch readback; WWDT/reset, voltage and
  temperature protection data.
- Preserve `OPEN_NO_BOARD_MEASUREMENTS`, Original P1, firmware startup
  policy and all fail-closed negative gates. Do not energize hardware
  from CI-generated fixtures or from this SOP alone.
