# E62 P1 — Original Guest startup reversal causality (source-only)

**Status:** diagnostic investigation; P0 Strict acceptance remains independent and unchanged. P1 scripted matrix remains **RED** if `direct20` or `steps` reverses.

## Fixed test contract

- Original ESCape32 Rel17.3 ELF SHA256:
  `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
- Fresh QEMU No-WFI / No-GDB boot per JSON PA26 DShot600 profile, 1 kHz continuous external-FC source.
- Original Guest owns PWM and its sector changes; real QEMU AQ/DB six-pad output enters the native current-continuous motor plant.
- Rotor angle is **unwrapped electrical angle**, whereas RPM is mechanical. ECX87 pole-pair count 21.
- BEMF flows from actual simulated rotor into CMPSS0, then ECAP1/CAP1, real Guest W1C acknowledgement, TIMG12 and Guest PWM. No Host Guest-MMIO/IRQ/synthetic-BEMF intervention.
- No acceptance threshold, sign-change rule, or motor calibration is modified by this investigation.

## Already observed source evidence

From P1 workflow [40551707627](https://github.com/cctsao1008/escape32-qemu/actions/runs/40551707627), before the optional FC 100ms/500ms ramp experiments:

| Original source profile | P1 verdict | P1 sign changes >=50 RPM | first 50ms after first-positive peak phase current | first 50ms minimum torque | first TIMG12 relative to first positive |
|---|---|---:|---:|---:|---:|
| smoke | PASS | 0 | 0.773 A | 0 Nm | 19.996 ms |
| gentle | PASS | 0 | 0.483 A | 0 Nm | 21.023 ms |
| direct20 | FAIL | 337 | 45.250 A | -3.509 Nm | 13.743 ms |
| steps | FAIL | 223 | 0 A | 0 Nm | 513.790 ms |

The `steps` first 50ms has **no energized drive** in this earlier trace, whereas its first >=50rpm is ~501.21ms after the first positive 10% command, near the **20%** transition. Accordingly the new ledger captures both first-positive and first-20%-command epochs. Do not interpret `steps` 50ms after 10% as a healthy startup.

A newer independent P1 workflow [40552428592](https://github.com/cctsao1008/escape32-qemu/actions/runs/40552428592) **does not reproduce the earlier steps inactivity**: with the same original step JSON and source model it measured 30.353 A peak phase current, -2.318 Nm torque and <=-50 RPM already **8.967ms after the initial 10% command**, before TIMG12 at 16.004ms. Its source P1 result was **328** significant direction changes. The prior run reported **223** direction changes with first 50RPM only after the later 20% stage. This is an actual run-to-run discrepancy, not an acceptance tolerance; timestamp/boot-state and startup-stage attribution must be audited. Thus the ledger preserves both the first-positive 10% anchor and the subsequent 20% anchor (it must never drop the early 10% events).

The same newer CI included physically clocked PA26 20% ramps: 100ms ramp **FAIL** with 238 significant reversals, whereas 500ms ramp **PASS** with 0. This implicates sensitivity to command slew rate / open-loop startup dynamics, but does **not** isolate whether original Guest startup and the uncalibrated plant disagree or establish firmware qualification.

The `direct20` rotor became <= -50 RPM at 7.209ms after the first positive 20% command, **before** its first observed TIMG12 at 13.743ms. Thus at least part of the negative-torque mechanical response occurs **before TIMG12-based commutation scheduling has been observed**. This points investigation toward direct-step starting-sector/rotor-angle/current transient or uncalibrated plant assumptions; subsequent CAP1/TIMG12 feedback can still amplify or sustain the oscillation. A strict before/after relationship is **not proof** of guest-firmware or plant fault.

## How to capture the next evidence, script-first

After provisioning the existing pinned QEMU and SIM_ONLY CFG as documented in `e62-native-p1-plan-and-gates.md`:

```bash
python3 tools/e62_native_scripted_test.py \
  --case smoke --case gentle --case direct20 --case steps \
  --output artifacts/e62-p1-scripted
# P1 exit code 1 must be retained: do not mask/redesign its failure.
python3 tools/native_p1_causality_ledger.py \
  --input-root artifacts/e62-p1-scripted \
  --output artifacts/e62-p1-scripted/e62-p1-causality.json
```

The P1 GitHub Actions workflow runs the read-only ledger with `if: always()` and publishes the JSON even when the upstream P1 strict matrix fails. Diagnostic exit code 0 means **evidence complete and counters consistent**, not that any motor qualification passed.

### What the JSON contains

- Source timestamps and deltas for first positive DShot, first command >=20%, first +/-50 RPM, first significant **sign change**, first <=-0.1 Nm torque marker and >=10 A phase-current marker.
- First post-anchor CMPSS filtered transition, CAP1, Guest CAP1 W1C, TIMG12, Guest TIMG12 W1C and PWM_PAIR. Their *times* and same-ns ordered source records, not invented functional causality.
- PWM_PAIR includes original decoded physical power pair, raw six-pad mask, raw AQ/DB gate-word and original PWM zero-event count. Invalid Hi/Lo overlap or source pair-ID disagreement is visible; no fabricated sector angle is used.
- First 50ms after **first positive** throttle and, separately, first 50ms after **first >=20%** throttle: signed RPM, **unwrapped electrical rotor angle**, three signed currents and torque. Every anomalous sample also links to the preceding actual source DShot stage/value.
- Around the first significant torque/speed anomaly, each event kind's nearest source neighbors reveal whether the original Guest had already entered a sensorless feedback cycle.
- `SWITCH` source events are explicitly bounded to **120ms after the first powered physical edge** by QEMU P0 instrumentation. Absence of later carrier-edge events does **not** demonstrate that later AQ/DB outputs stopped.

## Root-cause decision criteria (not pass waivers)

1. **Before first CAP1/TIMG12 feedback:** Compare start rotor electrical phase, first physically energized high/low pair, first negative torque and first large current, against the gentle/smoke initial pair and current direction. If first bad torque precedes feedback, investigate startup sector, rotor initial angle, force/EMF orientation and model parameters first.
2. **At closed-loop handoff:** Trace the exact source order `BEMF_FRONTEND → CMP_FILTER → CAP1 → CAP1_ACK → TIMG12 → TIMG12_ACK → PWM_PAIR`; compare phase mux, DAC threshold, signed speed, rotor angle and pair order around first reversal. Counts alone do not prove healthy commutation feedback.
3. **Model-vs-startup isolation:** Preserve fixed physics, source ELF and original PA26 profile while comparing 10% hold then 20% versus direct 20%, gradual ramp cases and separate frozen-switch/model identity checks already present in P0. Additional perturbations require new named SIM_ONLY experiments, never changing the strict acceptance case.
4. **No premature fix:** Do not lower 50 RPM reversal threshold, smooth/remove reverse samples, force Guest sector state, inject fake BEMF, coerce PWM/AQ/DB, or make the model silently clamp abnormal current/torque.

**Scope:** Uncalibrated 24V, no propeller, QEMU SIM_ONLY. Neither a PASS nor this diagnostic establishes physical ECX87/Queen Bee/12S qualification.


## 2026-10-28 forensic update: early CAP1 **rejection**, not an 11 ms timer delay

**Verified rebuilt-source baseline:** source-built QEMU on module-split
main passed [P0 strict run 40557926125](https://github.com/cctsao1008/escape32-qemu/actions/runs/40557926125),
No-WFI motor strict [40557926065](https://github.com/cctsao1008/escape32-qemu/actions/runs/40557926065).
P1 [40557926101](https://github.com/cctsao1008/escape32-qemu/actions/runs/40557926101)
remains **RED**, with smoke PASS (0 reversals), gentle PASS (0),
direct20 FAIL (337), steps FAIL (223), each FAIL solely
\`STARTUP_SIGNIFICANT_DIRECTION_REVERSAL\`.
The distinct 100ms ramp FAIL (238) and 500ms ramp PASS (0)
are diagnostic A/B, not substituted P1 acceptance.

### Original Rel17.3 firmware policy (not a new Host rule)

The pinned [Original \`src/main.c\`](https://github.com/cctsao1008/ESCape32/blob/b0204670515d2de0b2480b52273038f1ee13d30a/src/main.c)
initializes \`ival = 10000 << MOTOR_TIME_SHIFT\` at six-step start
and \`bemf_zero_cross_delay()\` returns **zero** when
\`capture_ticks < ival >> 1\`: a nominal **5,000 µs** startup
half-interval capture-rejection window. Its AM13E
[\`motor_bemf.c\`](https://github.com/cctsao1008/ESCape32/blob/b0204670515d2de0b2480b52273038f1ee13d30a/mcu/AM13E/hal/motor_bemf.c)
calls this original policy via \`am13e_app_motor_on_bemf_event()\`.
On rejection it increments \`rejected_events\` and leaves ECAP
capturing; on acceptance it updates \`crossing_epoch\` and
\`capture_stop()\`. Accepted crossings arm the *original* TIMG12
one-shot in [\`motor_event_timer.c\`](https://github.com/cctsao1008/ESCape32/blob/b0204670515d2de0b2480b52273038f1ee13d30a/mcu/AM13E/hal/motor_event_timer.c).
No host intervention or alternate timing control is part of this path.

### Source evidence after first real powered PWM_PAIR

The following uses read-only QEMU source events plus original P1 verdicts.
Timing origin is first *physical* PWM_PAIR **not** the first positive
DShot; this difference matters for the steps profile.

| Source replay | First CAP1 | Second CAP1 | Second CAP1 → first TIMG12 | First rotor electrical angle >= +90° within unchanged first physical pair |
|---|---:|---:|---:|---:|
| smoke (new run) | 16.782ms | none | 2.930ms | none before first commutation |
| gentle (new run) | 17.747ms | none | 2.993ms | none before first commutation |
| direct20 (new run) | **2.349ms** | **10.897ms** | **2.562ms** | **4.926ms** |
| steps, 223 reversals (new run) | **2.392ms** | **10.941ms** | **2.565ms** | **4.926ms** |
| steps, 328 reversals (older run) | **2.628ms** | **13.060ms** | **2.697ms** | **6.720ms** |

Source runs:
[40557926101](https://github.com/cctsao1008/escape32-qemu/actions/runs/40557926101)
and [40552428592](https://github.com/cctsao1008/escape32-qemu/actions/runs/40552428592).

Both failing scenarios record **two original physical CAP1 events and
two real Guest CAP1_ACK events before the first TIMG12**. The first
CAP1 occurs ~2–3ms after first physical energization, inside the
nominal 5ms original Rel17 startup rejection window. The second
occurs at ~11ms and TIMG12 follows only ~2.6ms later.

This is **consistent with the original Guest accepting only the second
capture**, not with an unexplained 11–13ms hardware timer latency
after a single accepted capture. The trace does not expose the exact
Guest-local \`crossing_epoch\` or computed \`capture_us\`, so this
causal classification remains **source-supported inference** rather
than a direct per-capture accepted/rejected log assertion.

The first physical pair is *identical* in all four cases:
Phase 2 high / Phase 1 low, six-pad mask \`0x18\`,
initial rotor phase about −30° electrical. For ideal positive
source-to-sink pair current, its forward-torque basis is
\`sqrt(3) * cos(theta_e)\`, with zero at +90°. In direct20 and
the powered steps runs, the rotor crosses +90° and recorded
current-based torque becomes negative **before first TIMG12
and before first new physical PWM pair**. In smoke/gentle,
the first commutation happens before that particular first-pair
angle is reached. This is a fixed-sector overrun, not evidence
that the first sector was wired backward.

### Engineering root-cause status

- **Observed mechanism:** rapid high command → fast simulated rotor
  acceleration with real AQ/DB pair → early filtered CMPSS edge and
  CAP1 → original startup minimum-half-interval rejection **consistent
  with trace** → rotor electrically outruns the unchanged sector →
  negative torque/reversal → later CAP1 → Guest TIMG12 → sector change.
- **Still open:** whether the simulated ECX87 rotor inertia/no-load
  dynamics unrealistically outrun the guest's original conservative
  5ms half-interval, versus whether the firmware startup policy
  requires a separately approved product adaptation. Do **not** assert
  that an uncalibrated simulation proves a real ESC firmware defect.
- **Reproducibility issue:** steps sometimes energizes at the initial
  10% command (328 reversals), and sometimes only at the later 20%
  command (~500ms into the profile, 223 reversals). Both need separate
  stage attribution; neither may be re-labelled PASS.
- **Immutable acceptance:** 50 RPM significant-reversal gate, original
  ELF identity, current-continuous plant, source-driven BEMF/CAP1,
  no-host-write rule, and original strict scenario JSON remain unchanged.

New diagnostic: \`tools/native_p1_first_feedback_latency.py\`; test:
\`tests/test_native_p1_first_feedback_latency.py\`; automated historic
comparison: \`.github/workflows/e62-native-p1-first-feedback-replay.yml\`.
The result is evidence only, never an alternate P1 qualification.
