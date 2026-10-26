# E62 EC 87 KV210 — One-command 12S-reference electrical BEMF campaign

**Entrypoint**

```bash
cd ~/github/escape32-qemu
git pull --ff-only
bash tools/run_e62_ecx87_frequency_batch.sh
```

The script first provisions **42 poles (21 pole pairs)** from the unchanged pinned original Rel17.3 ELF into a **SIM_ONLY preboot Cfg Flash**. This is the repo's existing `tools/sim_motor_cfg.py` functionality, **not** original Guest UART CLI execution.

Next the script executes **three independent QEMU Guest runs** with external physical-format PA26 DShot300, original Guest CRC and arming, fixed-frequency phase-independent U/V/W BEMF at **900, 1040 and 1285 electrical Hz**, and the existing source-pinned six-pad `--six-phase-audit` for the full **11-second** T01 (1-second ramp to 90%, 10-second 90% hold). Each frequency uses a separate config, original Guest instance, JSON evidence, and text log. Sector audit storage is explicitly capped at 100000 records to cover the theoretical high-frequency T01 envelope rather than the older 20000-sector default.

| External BEMF | Input eRPM | 21-pole-pair RPM equivalent |
|---:|---:|---:|
| 900 Hz | 54,000 | 2,571.43 RPM |
| 1040 Hz | 62,400 | 2,971.43 RPM |
| 1285 Hz | 77,100 | 3,671.43 RPM |

Generated files are under `artifacts/e62-ecx87-kv210-full-batch/`:

- `e62-g13b3-ecx87-kv210-cfg-flash.bin` (verified pre-boot Cfg)
- `e62-dshot300-<hz>-hz-bemf.json`
- `e62-dshot300-<hz>-hz-evidence.json`
- `e62-dshot300-<hz>-hz.log`
- `e62-dshot300-<hz>-hz-exit-code.txt`
- `batch-summary.json` (separate per-point verdicts and aggregate)

Any child test nonzero exit or incomplete/malformed evidence is marked **FAIL**. The batch continues to gather all three results and finally exits nonzero if any functional test fails, **or** if a separate provisional **±10% average commutation-rate screening** mismatches the ideal 6 sectors per electrical cycle. This screening is not an ESC spec and does **not** establish phase lock or rotor tracking even if it passes; examine `all_functional_points_pass` and `all_average_rate_screens_match` independently. Never reinterpret a full SITL functional PASS as a frequency-tracking PASS.

The simulator does **not** currently emulate a physical 12S LiPo voltage / propeller-load curve in this independent BEMF fixture. It does not change the original Guest motor-control tuning or protection thresholds. Only `telem_poles` changes in the simulated Config Flash. The new batch has been committed but has **not yet been executed with the user's pinned QEMU**; its PASS status must come from the generated Guest-backed evidence, not this file.

To review the aggregate:
```bash
jq '{overall_status, all_functional_points_pass, all_average_rate_screens_match, points: [.points[] | {electrical_hz, original_guest_functional_status, six_phase_sector_count, hold_timg12_services, observed_average_commutation_to_ideal_ratio, rate_screen_only_10percent}]}' artifacts/e62-ecx87-kv210-full-batch/batch-summary.json
```

## 2026-10-26 Guest-backed full results: systematic seven-cycle slip

Actual user-supplied batch summary and all three independent evidence files:

| Fixed independent external BEMF | Original Guest Hold TIMG12 / 10s | Observed steps/s | Expected steps/s | Observed ratio | Six-pad settled Guest PWM sectors |
|---:|---:|---:|---:|---:|---:|
| 900 Hz | 7,714 | 771.4 | 5,400 | 0.14285185 | 8,454 |
| 1,040 Hz | 8,915 | 891.5 | 6,240 | 0.14286859 | 9,770 |
| 1,285 Hz | 11,015 | 1,101.5 | 7,710 | 0.14286641 | 12,069 |

All three Guest functional runs PASS, no failed PWM sector settles; the
additional *average commutation-rate screen* FAILS at all three points.
The external three-phase sample center-sign-change counts are respectively
59,345 / 68,577 / 84,731 over the entire 11s (approximately the
expected 6*f*11 electrical input crossings). Original Guest source
CAP1 totals are 8,476 / 9,793 / 12,119, also near 1/7 of those crossings.
A physical three-phase input sign change is **not automatically an armed
CMPSS/ECAP1 capture**; do not call this raw ratio "hardware lost 6/7
captures". Do not attribute it to changing `telem_poles` from 14 to 42:
that is telemetry conversion, not a native sector timing parameter.
The exact same ~1/7 rate appeared in the earlier pre-provision 100 Hz
11-second experiment.

More direct temporal evidence from the original 1,040 Hz Guest WFI
`six_phase_audit.sectors`: TIMG12 service 5501 WFI bracket end at
6,210,750,000 ns; service 5507 at 6,217,500,000 ns. **6 Guest
sectors = 6.75 ms**, while **7 external 1040 Hz electrical
periods = 6.730769 ms**. The ~19 us discrepancy is within one
62.5 us Guest SysTick WFI bracket. Thus this is a deterministic
**roughly 7 electrical cycles per 6 Guest sectors** cadence, not a
mere mistaken aggregate unit conversion.

Original source-selected phase/polarity order remains:
U rising -> W falling -> V rising -> U falling -> W rising -> V falling.
With fixture U=sin(theta), V=sin(theta-120°), W=sin(theta+120°),
the nominal desired crossings are separated by 60 electrical degrees.
The observed ~420° sector cadence is consistent with the firmware
not being rearmed/ready in time to accept the **next** selected crossing
and catching that same edge on the following electrical revolution.
It does **not yet distinguish** native CAP1 blanking, timed 30° advance
commutation, late CMPSS filter rearm, or an input/route gate.
The previous source "functional PASS" explicitly did not qualify
edge-phase coherence; the run itself should remain PASS_FUNCTIONAL_ONLY
while the rate-screen FAIL remains visible.

No re-run is necessary for the first phase-slip investigation:
```bash
cd ~/github/escape32-qemu
git pull --ff-only
python3 tests/test_analyze_e62_independent_bemf_cycles.py
python3 tools/analyze_e62_independent_bemf_cycles.py \
  artifacts/e62-ecx87-kv210-full-batch/e62-dshot300-900-hz-evidence.json \
  artifacts/e62-ecx87-kv210-full-batch/e62-dshot300-1040-hz-evidence.json \
  artifacts/e62-ecx87-kv210-full-batch/e62-dshot300-1285-hz-evidence.json \
  --output artifacts/e62-ecx87-kv210-full-batch/offline-electrical-cycle-audit.json
```

That tool reads saved Guest WFI-bracketed original TIMG12 sector
timestamps and reports the distribution of apparent skipped **whole**
external electrical cycles between consecutive steps. It adds no
QEMU instrumentation, Guest writes, or synthetic IRQ. It does not
claim exact comparator edge timestamps or measured physical rotor phase.

## 2026-10-26 Offline full-Guest cycle-slip evidence and edge-phase alignment

The user ran the committed offline `analyze_e62_independent_bemf_cycles.py`
against three **original Guest full 11s** saved JSON files.

| Independent fixture | Consecutive Hold Guest intervals | Intervals matching 60deg + exactly one extra full electrical cycle | Median Guest electrical degrees / step | Normal expected |
|---|---:|---:|---:|---:|
| 900 Hz | 7,713 | 7,694 (99.75%) | 425.25deg | 60deg |
| 1,040 Hz | 8,914 | 8,894 (99.78%) | 421.20deg | 60deg |
| 1,285 Hz | 11,014 | 10,129 (91.97%) | 433.6875deg | 60deg |

The classification threshold in the offline diagnostic is a **wide
±0.20 electrical cycles = ±72deg**. The original WFI sample clock is
16 kHz / 62.5us per tick, equivalent to 20.25deg at 900 Hz, 23.4deg
at 1,040 Hz and 28.91deg at 1,285 Hz. The 885 unclassified
1,285 Hz intervals are **not independently proven to be malformed
captures, phase swaps or dropouts**.

**Stronger specific phasor alignment from original Guest
`six_phase_audit.sectors`, 1,040Hz hold at t ~6.21s:**

Original ELF BEMF code/route order, decoded from pinned
`src/commutation.h` and `mcu/AM13E/hal/motor_bemf.c`,
is Step1 U rising (theta=0deg), Step2 W falling (60deg),
Step3 V rising (120deg), Step4 U falling (180deg),
Step5 W rising (240deg), Step6 V falling (300deg).
Independent fixture defines U=sin(theta), V=sin(theta-120deg),
W=sin(theta+120deg), with theta(0)=-30deg. The original
`--bemf-config` is a fixture, **not the Guest's target rotor speed**.
The following theta values are derived from that independent
fixture's exact declared t0 and the saved real Guest WFI
`commutation_wfi_bracket_ns` end:

| Guest service | Step after service | WFI t (s) | Fixed-fixture theta | Next selected zero crossing | Angle forward to next crossing |
|---:|---:|---:|---:|---:|---:|
| 5501 | 6 | 6.2107500 | 34.8deg | V falling at 300deg | 265.2deg |
| 5502 | 1 | 6.2119375 | 119.4deg | U rising at 0deg | 240.6deg |
| 5503 | 2 | 6.2130000 | 157.2deg | W falling at 60deg | 262.8deg |
| 5504 | 3 | 6.2140625 | 195.0deg | V rising at 120deg | 285.0deg |
| 5505 | 4 | 6.2152500 | 279.6deg | U falling at 180deg | 260.4deg |
| 5506 | 5 | 6.2163125 | 317.4deg | W rising at 240deg | 282.6deg |
| 5507 | 6 | 6.2175000 | 42.0deg | V falling at 300deg | 258.0deg |

For example, when Guest enters Step6, the expected V falling
crossing at 300deg of the *current* external BEMF cycle has already
passed by approximately **94.8deg**; another V falling is about
**265.2deg** away. The **6 Guest sectors in 6.75ms** cover about
**7.02** independent electrical cycles. WFI time brackets are
not exact original CMPSS/ECAP IRQ timestamps, so do not present
these phase angles as exact hardware switching-edge measurements.

This **directly demonstrates a late-entered externally imposed
crossing window**, and explains how a fixed periodic input can
produce the observed 7-cycles-per-6-sectors alias. It does NOT
prove whether the lateness was introduced by Rel17 `ival` filtering,
`bemf_zero_cross_delay()`, delayed TIMG12 service, PWM ZERO
publication and rearm, or physical rotor phase mismatch in this
independent fixture. The original Rel17
`bemf_zero_cross_delay()` applies
`ival=(capture+3*ival)/4` and schedules a **positive**
post-CAP1 commutation delay
`(ival-(ival*cfg.timing>>5))/2` before the next sector; that
is a plausible self-reinforcing late-step mechanism if the
original Guest estimator has already accepted an entire extra
electrical revolution. **No unverified exact default timing
or root-cause attribution is asserted.**

Engineering implication: all three full Guest Functional SITL
results stay PASS, and the average-rate screens stay FAIL.
Do not 'fix' the result by dividing counters by 7, multiplying
Guest RPM by 7, changing `telem_poles`, artificially moving the
independent input crossings to Guest step times, inverting
comparator polarities, or skipping original CAP1/IRQ/blanking.
The input is not coupled to a motor plant: it is prescribed
external sine, while the original ESC controls outputs without
being able to change this source's rotor angle.

**Next causal experiment (only if actually needed):** one short
Guest run instrumenting *read-only* timestamps of source-pinned
original CAP1 accepted, TIMG12 scheduled/service, MCPWM ZERO
publication, and native CMPSS arm/rearm; compare each to the
next fixed-fixture target crossing on one coherent QEMU virtual
clock. Without these event timestamps, the exact stage responsible
for missing a crossing cannot be distinguished from phase-rate
totals alone. An improved *motor-coupled* 12S model is a different
experiment, requiring physical parameter/voltage/load contracts.
