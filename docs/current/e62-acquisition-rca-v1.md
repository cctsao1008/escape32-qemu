# E62 reference acquisition and startup diagnostics — v1

Scope: Issues #4, #5 and their #10 timeline dependency. SIM_ONLY diagnostics;
no firmware, QEMU peripheral, plant, original P1 threshold or production startup
policy changes. Nothing in this report closes either issue.

## Provenance and existing evidence

- QEMU repository base: `3f1ed18e53e115d13b5bad2450d4e315a3d5cea0`.
- Reviewed firmware source: `cctsao1008/ESCape32` commit
  `53953c04f7d857f3b402b3a19870605ed0471d8f`.
- Official TI SDK: `b872469ceef18de5e39a1d3acb0821ec158b44c7`.
- Original Rel17.3 ELF: `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
- Production Root Fixes ELF: `c49a7485af218966a2e3ec764de8d997d8ba478954dcad42b88c0c99e4f3c003`.
  This binary is NOT the original binary. It is unavailable in this cloud checkout.
- Experimental candidates require their own exact ELF/source/configuration hashes.
- Experimental QEMU analyzer reference: `204fe85a512fff9ea0cfdfe430a29132c52197c4`.
  No changes from that branch were merged.

Issue #4 cites historical robustness run
[40817417417](https://github.com/cctsao1008/escape32-qemu/actions/runs/40817417417):
+16 direct20 reversal before first CAP1; -16 ramp100 failed CAP1/TIMG12 handoff.
These are relative model ADC-code biases, not board calibration measurements.
The issue's summaries are available, but their raw artifacts are not present here
and GitHub API access is forbidden in the running environment. They are reported
historical results, not independently reverified raw traces in this change. The
old +/-16 matrix is not rerun or relabeled as new evidence. No synthetic midpoint
or offset code is installed as production calibration.

Existing [source event RCA](e62-issue5-source-event-rca-20261101.md) distinguishes
pre-feedback reversal in some restart cases from post-feedback instability in
47 V first demand. Its candidate `c82489db...` results must not be presented as
Original Guest qualification. Existing first-CAP rejection and fixed-stator
analysis on the experimental reference branch remains useful mechanistic
evidence, but does not qualify every firmware/profile combination.

The requested `sync-angle-030-repeat01`, `sync-angle-090-repeat01` and
`sync-angle-090-repeat02` logs, scenario, CFG and run metadata are unavailable.
Neither their -90 degree divergence nor their first-sector numerical results
can be newly reproduced from this workspace. Fresh published-task restoration
also remains unverified; this is the retained onboarding instance.

## Reference conversion and acquisition RCA

The reviewed firmware already implements the following chain:

1. `analog_sampling_backend.c` programs actual ADC scans. `analog_runtime.c`
   starts software-triggered scans of ADC0/1/2, records acquisition/completion
   tick and sample count, and publishes only after the coherent raw epoch is
   complete. These scans are sequential software requests, NOT simultaneous
   MCPWM-triggered ADC acquisition. Do not equate synchronized DAC publication
   with synchronized ADC sampling.
2. `analog_calibration_plan.c::am13e_bemf_reference_convert` converts the acquired
   VBUS code using explicit ADC span/low reference, offset and ppm gain, VBUS
   divider/offset, individual phase divider/offset/comparator correction, and
   independently specified DAC VDDA/gain/offset. Checked integer products and
   rounded ratios reject endpoints, invalid ranges and overflow. All three
   phase results are committed together. The DAC relation is `(D+1)*VDDA/4096`.
3. `am13e_app_adc_reference_fresh` requires both modular acquisition age and
   blackout epoch consistency. Completion does not reset acquisition age.
   Blackout invalidates samples and discards an in-flight old completion.
4. `motor_bemf.c::am13e_app_motor_bemf_stage` takes the selected floating phase's
   calibrated code and writes DAC shadow while capture is quarantined. Native
   carrier ZERO verifies the MCPWM4 SYNCPER/ZERO route, freshness and active DAC
   equality; an independently delayed DAC remains pending rather than assumed
   published when PWM global load completes.
5. `compctl` selects the phase mux and ECAP edge. Native CMPSS is phase > DACH;
   the port reverses the edge relation from the reference > phase convention.
   Comparator inversion, filtered output and ECAP edge must be audited together;
   a filtered level alone does not prove polarity correctness.
6. Missing initial calibration cannot authorize capture/start. Route mismatch,
   stale/invalid reference and active-code mismatch exercise actual fatal
   shutdown: gate inactive, pads disconnected, ECAP capture/counter stopped,
   PWM frozen, pending publication cleared. Accepted crossing epochs advance
   only on accepted events; DAC publication is not itself a crossing.

This supports a cause map, not a new proven firmware defect: reference bias may
move or eliminate crossings; phase selection/polarity may select the wrong edge;
publication delay must hold capture inactive; low-BEMF quantization may make
reacquisition unobservable. These mechanisms are distinct from switching noise,
interval-policy rejection and the model's torque/angle dynamics. No isolated
firmware fix is justified by the new evidence; none is included.

## Reused negative tests and limitations

`tools/ci/check_e62_reference_contract.sh FW SDK` pins both source trees and runs
their existing full host and register regressions unchanged. This is host/register
integration with the production source and official SDK, NOT QEMU/ADC silicon or
motor qualification. Fixtures are explicitly synthetic electrical definitions.

Observed passing coverage includes:

- ADC/DAC unequal references/dividers, gain/offset, rounding, endpoints, overflow,
  and freshness across tick wrap;
- missing initial sample; coherent sample identity, busy skips and sequence wrap;
- blackout invalidation, late old completion discard and post-blackout acquisition;
- wrong CMPSS sync route, wrong MCPWM sync selection, active DAC mismatch,
  stale/invalid sample and fault during pending publication;
- delayed DAC loading, timeout while pending, phase-specific publication for six
  steps and both directions, and no capture before independent DAC completion;
- accepted/rejected capture epochs, timer delay, wrap, delayed ZERO, timeout and
  restart.

Live incorrect-mux corruption is not independently established by the above
phase-association positive tests. A native QEMU dynamic-reference mismatch
matrix remains open. The current source-event schema exposes phase ADC EOC/read
and comparator phase/DAC values but does not expose the full calibrated-reference
sample identity, blackout epoch, route and active-publication association.
Therefore those events cannot prove freshness/publication correctness end to end.

## Offline analyzer

Run from the checkout:

```sh
python3 tools/e62_acquisition_timeline.py run.manifest.json --output timeline.json
python3 tools/e62_acquisition_timeline.py run.manifest.json \
  --compare repeat.manifest.json --output comparison.json
python3 -m unittest tests.test_e62_acquisition_timeline tests.test_e62_issue5_cap1_timer_audit -v
bash tools/ci/check_e62_reference_contract.sh /path/to/pinned/firmware /path/to/pinned/sdk
```

The manifest is a JSON object with `files` paths for `events`, `scenario`, `cfg`,
`elf`, `qemu`, `evidence` (relative to the manifest or absolute), and a `<name>_sha256` for
all six. It also requires `firmware_class` (`original_rel17_3`,
`production_root_fixes`, `experimental_candidate`), `firmware_commit`,
`qemu_commit`, `profile_id`, nonempty `effective_parameters` from readback,
a nonempty `experiment_contract` for clock/BEMF/noise/runtime options,
`timebase: QEMU_CLOCK_VIRTUAL`, `host_guest_register_writes: false`, and explicit
positive diagnostic `rotor_max_age_ns` and `switch_max_age_ns`. These ages are
coverage budgets, not altered P1 acceptance. SHA validation binds all six inputs;
source/build/readback metadata must still be supplied with the archived run.

The analyzer preserves sequence and absolute nanoseconds, uses actual DShot
frame anchors, checks canonical encoded commands and the existing P1 dispatch
contract, reports per-boundary preceding/following rotor samples and age, and
retains pad/gate events separately with their freshness. It carries audio clock
mode across boundaries as an INFERRED candidate, not private audio ownership.
Missing clock-mode events remain not observable. It reports comparator sense/DAC
codes but explicitly does not invent sample identity or publication proof.

Per-stage first power-pair, filter, capture, ACK/read, timer load/start, expiry/ACK
and first negative-RPM sample remain raw source references. Capture windows use
the existing read/ACK versus timer-programming classifier; the final capture is
right-censored. Pair sequence alone does not prove torque-positive alignment.
A missing SWITCH after a bounded logging window is incomplete pad evidence,
not zero switching. No boundary interpolation is performed.

Matched comparisons require identical firmware family/hash, QEMU/CFG/scenario
hashes, profile and effective parameters. They locate the earliest exact recorded
event mismatch, including virtual-time differences. This does not attribute
causality to QEMU scheduling, firmware policy or the plant. Missing/truncated or
unmatched inputs fail closed; valid chronology never sets `p1_qualified`.

## Qualification and next experiments

First Startup: NOT QUALIFIED by this diagnostic change.
Flying Restart: NOT QUALIFIED; historical counterexamples remain failures.
Reference acquisition: host/register contract verified; native source publication
identity and full +/-16 cause map remain incomplete.

Issue #5's active scope is SIM_ONLY. Hardware/BOM measurements are not its
closure blockers. Required software evidence still includes source-owned first
start, near-stall, 300/1500/3000ms coast, second demand and both applicable
rotations with effective versioned motor/analog/clock/noise profiles. A safe
no-rearm can pass rejection safety only, not re-acquisition. No threshold waiver.

Before another A/B, recover and verify prior raw archives. Pin the firmware
family/source/ELF, CFG, QEMU binary/build flags, model readback, initial pose,
scenario and time origin. Hypotheses should isolate reference validity versus
publication timing versus interval-policy rejection, holding other inputs fixed.
The three Issue #10 repeats must be aligned before assigning their later
trajectory divergence to audio or startup. Additional instrumentation, if needed,
must be observational, separately reviewed and must not synthesize feedback.

The new workflow runs offline tests and the existing pinned host/register
integration. It does not hide P1 failures, publish firmware, merge or close issues.

## Current-cloud native integration (original binary, separate from historical +/-16)

The real native probe completed 5,100 source-owned frames in the existing
300ms-coast scenario with native ADC BEMF enabled and no source-model fault.
Firmware family: Original Rel17.3, NOT Production Root Fixes. This original
binary is a legacy-reference control, not a native dynamic-SC5 qualification.

- QEMU SHA256: `d5f4f5102469bb6dc4012682f4d7101d01b7c26fe7c3b29cd01a8c685ba7b943`.
- CFG SHA256: `64d7a54624b16b5978526ea354dc57ded2b20377ec54945a591399d564aab0e4`.
- Scenario SHA256: `891b9b7503f0933d58310fbd8541139d6fec69f8c1b35212b34c88b6c4ffce20`.
- Effective model readback: KV147, 24,000mV bus, -30,000mdeg initial electrical
  angle, phase R=53,000 micro-ohm, phase L=24,000nH, terminal Kt=64,900 micro-Nm/A.
- MCPWM root is the pinned main-source 100MHz constant. This is not the Issue #10
  200MHz/47V/production-root-fixes evidence set.

Repeat01 boundary samples (all preceding the actual boundary by approximately
0.765ms; angles below are electrical):

| Boundary virtual ns | Prior RPM | Unwrapped rad | Wrapped degrees | U/V/W A | Torque Nm |
|---:|---:|---:|---:|---|---:|
| 1500000100 demand1 | 0 | -0.524 | 329.977 | 0 / 0 / 0 | 0 |
| 3000000100 coast | 231.669 | 137.989 | 346.187 | -43.219 / 43.219 / 0 | -0.781385 |
| 3300000100 demand2 | 16.366 | 155.599 | 275.166 | 0 / 0 / 0 | 0 |
| 4800000100 final neutral | -262.487 | 291.606 | 147.793 | 39.587 / -39.587 / 0 | 0.098281 |

There is no prior rotor sample at the first neutral frame (vns=100), and the
bounded SWITCH records do not provide fresh gate-state evidence at later
boundaries. The report marks both cases incomplete rather than substituting
configured state or treating last-known gates as current gates.

Native wiring smoke: PASS, strict stability explicitly still OPEN. The existing
P1 CLI rejects the ADC-extended raw trace because its event whitelist lacks
`ADC_PHASE_EOC/READ`. That parser failure is preserved. Calling the unchanged
P1 `analyze` function with the new lossless observer-aware parser independently
returns FAIL with `STARTUP_SIGNIFICANT_DIRECTION_REVERSAL`; no events are filtered
out and no criterion is changed. Repeat01 demand1 RPM range -279.260..354.643;
demand2 -279.541..314.075. Each positive stage has 262 significant direction
changes under the existing criteria. Neither startup nor restart is qualified.

Reproduction from the repository root after sourcing the cloud tool activation:

```sh
python3 tools/sim_motor_cfg.py --sim-only-opt-in \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --motor-profile ecx87-kv147 \
  --output artifacts/e62-acquisition/e62-g13b3-original-cfg-flash.bin
python3 tests/e62_autonomous_native_motor_probe.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-acquisition/e62-g13b3-original-cfg-flash.bin \
  --scenario scenarios/e62-experimental-two-demand-coast-short300.json \
  --sim-motor-profile ecx87-kv147 --sim-native-adc-bemf \
  --sim-initial-electrical-degrees -30 --differential-sync-start \
  --artifact artifacts/e62-acquisition/repeat01.json --wall-timeout-s 300
```

Repeat02 uses exactly the same command with only the output artifact name changed.
This is a matched A/A repeatability check, not a control-policy A/B experiment.
The hypothesis is that synchronized boot and identical source-owned inputs yield
identical recorded chronology; neither a match nor a divergence identifies the
cause of the motor instability by itself. Historical offset A/B results are kept
separate, and no unavailable experimental ELF is substituted.

Raw current-cloud evidence and byte-pinned manifests are retained under ignored
`artifacts/e62-acquisition/`; these files are not committed as fabricated fixtures
or guaranteed to survive a future task. Archive the raw bundle before relying on
this report for issue acceptance. The committed unit fixtures are synthetic and
never count as motor or reference-publication qualification.

## Matched repeat outcome and first-sector interpretation

Both A/A runs completed 5,100 frames, wiring smoke PASS, no model fault. Both
failed the unchanged P1 direction-reversal criterion. The byte-pinned summary is
[e62-acquisition-evidence-v1.json](e62-acquisition-evidence-v1.json); it is a
summary, not a replacement for archived raw logs.

The earliest exact recorded mismatch is event seq 7409, `WWDT_FEED`:
repeat01 vns=563043228 versus repeat02 vns=563043260, identical data
`[530,48,0,0,0,0]`. This 32ns difference precedes demand1. It falsifies identical
recorded chronology for these two synchronized runs. It does not identify a
QEMU scheduling bug, a firmware policy bug, a clock-speed error, or the cause of
later rotor divergence. A subsequent record/replay or scheduler investigation
must preserve the exact inputs and observational interfaces before attribution.

Repeat02 demand2's preceding sample is +13.019 RPM; its final-neutral boundary
sample is +265.470 RPM versus repeat01's -262.487 RPM. These are finite-resolution
sampled states, not proof of the continuous trajectory between them. Both runs
still fail independently; selecting the more favorable endpoint would be invalid.

Repeat01 demand1: first physical pair at +0.246932ms is pair 8 / mask 24,
W-positive, V-negative, U floating. First CMP_FILTER/CAP1 at +3.028300ms selects
mux phase 0 (U), consistent with that first pair. ACK +3.028988ms and read
+3.029104ms occur with no T12_LOAD/START before the next CAP1. This is
READ_WITHOUT_TIMER_PROGRAMMING, consistent with early-edge rejection but not a
direct observation of `ival`, callback return, or an internal reject branch.
The first sampled negative RPM is -41.491 at +8.235060ms; first TIMG12 is
+16.771100ms. The earlier T12_LOAD at +0.079268ms is the startup 65,535us timeout,
not a commutation schedule following the first capture.

Repeat01 demand2: pair 3 / mask 33 at +0.246992ms is U-positive, W-negative,
V floating. First source CMP_FILTER/CAP1 at +7.172332ms selects mux phase 1 (V).
First sampled negative RPM (-27.863) occurs at +1.235092ms, before that capture
and before TIMG12 +9.486500ms. Thus changing a later capture filter alone cannot
explain away the earliest reverse sample. Residual phase/current, remembered
sector, and uncalibrated plant response remain separate hypotheses. The numerical
negative-sample markers here are not changed significant-reversal thresholds.

Polarity registers and calibrated-reference publication identity are not directly
exposed by these filter events. Digitally consistent first-pair/mux selection
cannot prove correct phase wiring, edge polarity or electromagnetic torque sign.
No genuine firmware integration defect has been established by these runs, so
there is no firmware fix mixed into the diagnostic branch.

## Local regression results and remaining gates

- New offline analyzer: 10 unit tests PASS (fixtures explicitly synthetic).
- Analyzer + existing CAP1 classifier + unchanged P1 unit tests: 25 tests PASS.
- Existing autonomous host suite: 62 tests and repository audit PASS.
- Pinned firmware full host script: 107 named groups PASS.
- Pinned official-SDK motor-register script: PASS, including SC5 negative paths.
- New combined pinned-source shell wrapper: PASS.
- Native A/A wiring smoke: two PASS; P1 criteria: two FAIL, direction reversal.
- Standard P1 CLI with extended ADC event log: FAIL, unknown observer event type.
- No new +/-16 control experiment, no calibration/physics/acceptance changes.

Remaining gates: recover historical +/-16 raw cause-map evidence; acquire the
Production Root Fixes binary and three Issue #10 trace bundles; establish native
dynamic-reference sample/epoch/phase/publication observability; distinguish timing
repeatability from motor/model causality; run the independent near-stall,
300/1500/3000ms, both-direction qualification matrix with complete profiles and
unchanged thresholds. API access is required to publish the reviewable PR; saving
an api.github.com network requirement does not apply it to this running machine.

## Lifecycle replay extension

`tools/e62_lifecycle_alignment.py MANIFEST --output REPORT` now preserves the
complete requested source-event overlay, clock-mode intervals (including a
candidate audio interval that began before a demand), all actual command-stage
anchors and boundary sample ages. Software-private arming/audio states remain
inferred. Main-source traces without clock instrumentation do not acquire
invented audio intervals. Four focused tests exercise overlap, exit, absent
clock evidence and timestamp preservation. Both real current-cloud Original
Guest traces replay successfully; their private lifecycle/reference verdicts
remain incomplete. A separate source-equivalent runtime cohort is in progress;
it is not relabeled as the missing historical c49a7485 cohort.
