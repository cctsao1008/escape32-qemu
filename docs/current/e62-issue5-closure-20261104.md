# E62 AM13E Issue #5 closure and productionization status (2026-11-04)

## Scope

This document records the current QEMU evidence for E62 AM13E Issue #5 and
separates confirmed AM13E integration fixes from the remaining sensorless
restart behavior. All motor/rotor conclusions here are **SIM_ONLY** and are
not hardware qualification.

Formal diagnostic condition:

- motor profile: `ecx87-kv210-47v-no-prop`
- VBUS: 47 V
- initial electrical angle: -30 deg
- BEMF waveform: `historical_sine`
- MCPWM root: 200 MHz
- native ADC/BEMF enabled
- DShot: 1 kHz physical DShot600 source
- baseline scenario: `e62-experimental-two-demand-coast-short300.json`
  - 1500 ms neutral
  - 1500 ms 20% demand
  - 300 ms coast
  - 1500 ms 20% demand
  - 300 ms coast

## Resolved AM13E integration defects

### 1. Acquisition-stage false desync reset

The legacy six-commutation desync detector compared a stale 1000 us anchor
against the rapidly converging AM13E acquisition interval. This repeatedly
reset `sync` during otherwise valid initial BEMF acquisition.

Firmware fix:

- `2f04c47905ed3115d6af20a2e5759de3c9ec879e`
- defer/re-baseline the desync guard while `sync < 6`
- retain the original Rel17 guard after synchronization

Production extraction uses the same behavior without the experimental
candidate-v2 commentary.

### 2. CMPSS digital-filter initialization ordering

The AM13E port initialized the CMPSS filter while the selected comparator was
disabled. The filter must be seeded after the selected phase is routed and the
comparator is enabled.

Firmware fix:

- `5edbb09fdc68a7d9e02c0407676b7f866fea9025`
- enable selected CMPSS0 comparator before `DL_CMPSSLITE_initFilterHigh()`

### 3. Compile-time ideal BEMF reference removed

Firmware must not know whether it is running on silicon or QEMU.

Firmware cleanup:

- `5ff0bf18cc49c93b8a10f15d3aa5f53742984779`
- reject `AM13E_BEMF_INITIAL_DAC_CODE`
- use board-calibrated runtime ADC -> BEMF reference -> CMPSS DACH path

### 4. QEMU-only model corrections

The following are simulator/model corrections and must not be copied into
firmware:

- CMPSS DACH transfer function corrected to TI DAC semantics
- VBUS sourced through the native ADC/runtime-calibration path
- PWM history observer no longer refreshes current waveform history for
  shadow/current-level-neutral register writes
- final strict PWM provenance result:
  - `native_pwm_invalid_level_events=0`
  - `native_pwm_invalid_eval_events=0`
  - `native_pwm_invalid_late_events=0`
  - `native_pwm_invalid_drive_window_events=0`
  - `wiring_failure_reasons=[]`
  - `PWM_HIST_LATE count=0`

PWM provenance is therefore **CLOSED** for this QEMU configuration.

## Remaining behavior: near-zero sensorless restart

The 300 ms coast case is not an AM13E peripheral-loss signature.

Observed demand2 behavior:

- six-step pair order remains correct:
  `8 -> 2 -> 3 -> 6 -> 4 -> 7`
- CMPSS, CAP1, TIMG12 and PWM pair activity continue through demand2
- rotor repeatedly crosses zero speed
- demand1 pair/rotor phase is tightly locked (`R ~= 0.999`)
- demand2 is initially phase-hunting, then enters a stable wrong-phase
  attractor
- phase error grouped by actual rotor direction:
  - forward > 50 rpm: mean +34.8 deg, R=0.804
  - reverse < -50 rpm: mean +177.8 deg, R=0.982

The approximately 180-degree reverse-speed phase inversion is consistent with
this SIM_ONLY mechanism:

1. restart begins near zero speed using retained commutation state;
2. an initially wrong electrical phase can produce reverse torque;
3. physical BEMF changes polarity when rotor speed changes sign;
4. firmware capture-edge polarity remains tied to commanded direction;
5. the sensorless loop can therefore accept the opposite crossing and
   phase-slip/reacquire repeatedly.

This is a **control-policy / sensorless restart** issue, not current evidence
of MCPWM/CMPSS/ECAP port failure.

## Decisive A/B: positive-residual restart

Do one controlled A/B before expanding the matrix:

- A: existing 300 ms coast
  `scenarios/e62-experimental-two-demand-coast-short300.json`
- B: 100 ms coast
  `scenarios/e62-experimental-two-demand-coast-short100.json`

Keep all other Guest/QEMU/profile/configuration inputs identical.

The 100 ms case is intended to restart while the rotor still has a clear
positive residual direction. It is not a product threshold claim.

Acceptance evidence for the 100 ms case:

- demand2 rotor does not enter sustained negative-speed hunting
- reverse-speed phase bucket disappears or becomes negligible
- demand2 pair phase concentration approaches demand1
- demand2 accelerates toward the demand1 steady-state regime
- all strict PWM provenance counters remain zero

Analyze each P0 log with:

```bash
python3 tools/e62_p0_stage_counts.py <artifact>.p0.events.log
```

The analyzer derives the demand2 time window from DShot stages, so the same
tool is valid for both 100 ms and 300 ms scenarios.

## Candidate-v2 acquisition policy review

The experimental candidate-v2 branch contains:

```c
if (sync < 6 && capture_ticks >= 400 && capture_ticks <= 4500) {
    ival = capture_ticks;
    fast = 0;
    return max((capture_ticks * (32 - cfg.timing)) >> 6, 1);
}
```

Evidence so far:

- 400 us versus 350 us A/B did not identify this floor as the Issue #5 root
  cause
- the real acquisition false-reset root was the stale legacy desync anchor
- therefore this candidate-v2 policy is **not included automatically** in the
  clean production extraction

Decision remains OPEN: retain only if separately justified as intended product
acquisition behavior.

## Clean production extraction

A clean firmware branch has been created from `am13e-port-v2`:

`cleanup/e62-issue5-production-root-fixes-20261104`

Base:

`53953c04f7d857f3b402b3a19870605ed0471d8f`

Included commits:

- `f8649d78d9cd6bb85f0b328c531327b1fd824408`
  - defer AM13E desync guard until BEMF sync
- `06f5aed31d281e1095407ef6710c69652dd8e147`
  - CMPSS enable/FILINIT ordering
  - remove compile-time ideal BEMF reference seed

The branch intentionally excludes:

- candidate-v2 400 us acquisition policy
- QEMU observer/model fixes
- near-zero restart policy changes
- Issue #5 diagnostic-only instrumentation

It must be built/regressed before any production merge.

## Required regression before production merge

1. AM13E compile and link with pinned TI SDK/toolchain.
2. Existing host/HAL tests.
3. Original DShot receive and throttle path.
4. Initial 47 V Issue #5 acquisition scenario.
5. CMPSS/ECAP/TIMG12 capture/commutation path.
6. zero-throttle teardown and restart.
7. fault/trip shutdown paths.
8. verify no `AM13E_BEMF_INITIAL_DAC_CODE` build dependency remains.
9. verify candidate-v2 acquisition policy is absent unless separately approved.

## Hardware validation still required

Simulation does not qualify:

- actual E62 VBUS/phase divider calibration
- CMPSS propagation and filter latency
- ECAP timing on silicon
- MCPWM dead-band and gate-driver timing
- current-sense / overcurrent behavior
- MOSFET and DC-link thermal behavior
- real EC87 BEMF waveform and phase relationship
- coast/flying restart with real motor/propeller inertia
- near-zero restart behavior
- protection interaction under 47 V loaded operation

## Closure rule

Issue #5 AM13E integration fixes can be considered QEMU-closed after:

1. the 100 ms positive-residual A/B confirms normal reacquisition without
   reopening peripheral/provenance failures; and
2. the clean production extraction passes regression.

Near-zero restart remains a separate control-policy item and must not be
silently counted as an AM13E peripheral regression.
