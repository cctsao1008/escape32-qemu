# E62 SIM_ONLY 3 ms / quarter CAP1 — six-scenario verification and Motor Output start fault (2026-10-29)

## Classification

**SIX-SCENARIO EXPERIMENTAL NON-SHA MOTOR/OBSERVABILITY PASS; NOT Original Rel17.3 P1; NOT hardware qualification.**

- Original Rel17.3 SHA256 (immutable): `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`
- Exact original-derived three-instruction candidate SHA256: `0975dd2169b308e1b4a3d131078f744ab6c0f6efa6acc65c7953d2a5f9ecfcd5`
- Candidate: startup 10000 -> 3000 us at two anchored Thumb-2 sites; early BEMF filter `ival/2` -> `ival/4` at one anchored site; original timeout/desync reset left unchanged. Nine changed ELF bytes total.
- Motor model: corrected ECX87 KV147 SIM_ONLY phase normalization, unchanged for the candidate A/B.
- Evidence: [six-scenario CI #40809353792](https://github.com/cctsao1008/escape32-qemu/actions/runs/40809353792). All three jobs completed successfully, and **every per-scenario JSON** was independently checked rather than inferring PASS from a green job.
- This harness runs the **unchanged** `native_p1_qualification.py` analyzer, which correctly exits nonzero for all six candidate ELFs due to `ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN`. All non-SHA P1 observability failures are empty. The Original strict P1 remains FAIL.

## Full six unchanged-scenario result

| Scenario | Peak abs RPM (sim) | Physical PWM_PAIR | Guest CAP1 W1C ACK | Guest TIMG12 W1C ACK | Significant rotor reversals | Non-SHA failures | Classification |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| smoke | 834.695 | 1436 | 1435 | 1435 | 0 | none | SIM_ONLY diagnostic PASS |
| gentle | 445.493 | 1961 | 1961 | 1960 | 0 | none | SIM_ONLY diagnostic PASS |
| direct20 | 835.086 | 2594 | 2593 | 2593 | 0 | none | SIM_ONLY diagnostic PASS |
| steps | 1214.935 | 2112 | 2111 | 2111 | 0 | none | SIM_ONLY diagnostic PASS |
| ramp20_100ms | 835.166 | 1808 | 1807 | 1807 | 0 | none | SIM_ONLY diagnostic PASS |
| ramp20_500ms | 835.923 | 2182 | 2181 | 2181 | 0 | none | SIM_ONLY diagnostic PASS |

Every case: `probe_exit_code=0`, `unchanged_original_analyzer_exit_code=1`, `strict_original_p1_sha_guard_held=true`, `active_speed_signs_above_50rpm=[1]`, `significant_rotor_direction_changes=0`, `diagnostic_mechanical_closed_loop_criteria_met=true`, `non_sha_failures=[]`.

**Important gate hardening**: the experimental candidate harness previously returned 0 if source observations existed and the Original SHA gate was held, *even when an actual non-SHA motor criterion failed*. This was corrected by [commit 79310dc](https://github.com/cctsao1008/escape32-qemu/commit/79310dc545c246b1decf89f623a1aed343ba354e) so a candidate test job now exits nonzero if **any** original non-SHA mechanical / observability criterion fails. This does not waive Original P1.

## Separately source-built Motor Output=1 issue: precise fault boundary

Older source-built experiment [#40792045153](https://github.com/cctsao1008/escape32-qemu/actions/runs/40792045153) was based on ESCape32 source commit `0f2c3960085641291f479dbd3e945a250dc48a12`; its archived control ELF SHA256 was `2fd74ae6943d5720acdb6ed0366463aba7f6a7a8655532e903e5426c1aa30669`.

The downloaded original artifact (`e62-early-cap1-direct20-exp-not-original-guest`, artifact ID `12862197791`) contains read-only QMP measurements made after the 3300 DShot source frames:

| Symbol | Observed value | Interpretation |
| --- | --- | --- |
| `e62_sim_runtime_fault_reason` | `6` | `am13e_app_motor_commutation_enable()` rejected `am13e_motor_output_start()` return=0 |
| `e62_sim_runtime_fault_prestate` | `0x04` | audio_owner=0, initialized=1, latched=0, timebase_running=0 before shutdown |
| `e62_sim_runtime_fault_caller_pc` | `0xA7D5` | Supports fault callsite, not individual nested output-start predicate |
| post-fault `fault_latched` | 1 | Set during real fault shutdown; not proof it was set before failure |
| physical CAP1/TIMG12 | 0/0 | Fault prevented feedback-driven motor operation |

**Old instrumentation cannot identify which individual condition within `am13e_motor_output_start()` returned false.** Do not claim that output-start reject subcode 3 was measured in this old binary.

The source update from `0f2c396` to `907c5c3` comprises only:
1. SIM_ONLY read-only output-start rejection marker around the existing checks, without altering their boolean acceptance or Trip/OC/nFAULT policy ([commit d467ab4](https://github.com/cctsao1008/ESCape32/commit/d467ab4b35fdf1a0996680649498004e23f52001)).
2. A SIM_ONLY board fixture `AM13E_BEMF_INITIAL_DAC_CODE=2048` ([commit 907c5c3](https://github.com/cctsao1008/ESCape32/commit/907c5c3285ea1eebafe247c918c882609bf2db16)), matched to QEMU frontend `1.65V + 0.02*BEMF(V)` on 3.3V/12-bit scale.

Relevant source chain:
`am13e_app_motor_commutation_enable(1)` -> `am13e_motor_output_start()` -> `am13e_app_motor_bemf_reference_start_ready()`.
For non-SC5 builds, the last routine requires `initialized && ((!selected_code && !pending_code) || reference_ready)`. Without a provisioned BEMF DAC and with an active sensorless BEMF selection, `reference_ready=0` blocks startup by design. `am13e_app_motor_bemf_init()` calls `am13e_app_motor_bemf_reference_set(2048)` only if the fixture explicitly provides `AM13E_BEMF_INITIAL_DAC_CODE`.

The paired rebuilt-source CI [#40806638889](https://github.com/cctsao1008/escape32-qemu/actions/runs/40806638889) completed Direct20 with both separate Motor Output=1 source builds. The final passive QMP snapshots for both have `e62_sim_motor_output_start_reject=0`, `e62_sim_runtime_fault_reason=0` and `fault_latched=0`; physical CAP1/TIMG12 and six-step PWM returned. The five other source-built profiles passed independently in [#40806799665](https://github.com/cctsao1008/escape32-qemu/actions/runs/40806799665).

**RCA classification:** old SIM_ONLY fixture missing a valid modeled BEMF zero-reference seed is the best-supported root cause of the motor-output-start fail-closed rejection. The observed before/after and code diff establish strong causal support; the historical source ELF did not log the individual nested rejection code, so a strict sub-branch proof would require a negative control with the later diagnostic marker and deliberately omitted SIM_ONLY seed. Do not bypass this gate.

## Safety boundary and open verification

- `AM13E_MOTOR_OUTPUT_CONFIGURED=1` is **mandatory** for all source-built motor experiments; compile-time `AM13E_E62_REQUIRE_MOTOR_OUTPUT=1` plus complete SIM_ONLY board fixture. `=0` Reference firmware is not a motor qualification configuration.
- The `2048` DAC seed is derived solely from the QEMU analog frontend. It is **not** measured real-PCB BEMF Vdc/2 calibration, not a released OC threshold and not hardware permission.
- Preserve all gate dead-time, hardware nFAULT, three-phase OC/Trip, AQ, and fault-latch checks. Do not create positive tests by Guest CAP1/TIMG12 injections.
- No source-built/runtime equivalence to the pinned Original Guest has been proved just by matching mechanical direction. The rebuilt control/candidate are separate ELFs with separate SHA values.
- Global `ival/4` increases susceptibility to spurious early CAP1 from switching noise. Noise immunity, blanking, dynamic capture window, real electrical/propeller loading, reverse-demand cases, startup/restart, gate/dead-time, and thermal/OC Trip must still be qualified.
- Earlier 3ms/quarter Direct20 experiment includes negative electromagnetic torque samples even though RPM never goes significantly negative. Never represent the improvement as torque ripple elimination.

No Original P0/P1 threshold, source phase-order, board safety policy, or baseline ELF was changed by this report.

## Raw physical-event negative-torque audit (same six original scenarios)

The following values were independently computed by streaming each original
`.p0.events.log` archived in successful six-scenario run
[#40809353792](https://github.com/cctsao1008/escape32-qemu/actions/runs/40809353792),
using the strict analyzer's scenario-reported
`input_positive_start_virtual_ns` and `input_positive_end_virtual_ns`.
All six have zero sampled rotor events <= -50rpm, but all have some
negative electromagnetic torque samples below -0.1 Nm; this is NOT a
torque-ripple-free result.

| Scenario | Positive commanded window (ms) | Number of ROTOR samples with torque < -0.1 Nm | Min torque (Nm) | First physical CAP1/Guest CAP1_ACK after positive onset (ms) | First TIMG12/Guest TIMG12_ACK after positive onset (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| smoke | 1295 | 171 | -0.27323 | 21.567 | 23.466 |
| gentle | 2980 | 228 | -0.19178 | 23.084 | 25.077 |
| direct20 | 1500 | 375 | -0.28063 | 3.065 | 3.807 |
| steps | 1500 | 194 | -0.27478 | 503.107 | 503.852 |
| ramp20_100ms | 1095 | 238 | -0.28893 | 11.597 | 12.873 |
| ramp20_500ms | 1495 | 241 | -0.26264 | 20.303 | 22.123 |

`steps` includes a positive-demand interval preceding its actual motor
startup/engagement by ~500 ms; therefore its first CAP1 latency is *not*
a bare startup time and must not be compared to Direct20 without accounting
for the command stages.

The event field interpretation follows `tools/experimental_e62_bemf_ab.py`:
`ROTOR` field `f` is electromagnetic torque in micro-Nm, thus
`f < -100000` means torque < -0.1 Nm. Source direction criterion uses
`ROTOR.a <= -50000` for -50 rpm. These are observational diagnostics,
not a newly relaxed P1 gate.

Direct20 first sequence relative to first positive DShot:
- +0.284 ms first physical PWM_PAIR
- +3.065 ms CAP1 and Guest CAP1_ACK
- +3.807 ms TIMG12 and Guest TIMG12_ACK
- +3.867 ms next physical PWM_PAIR

This preserves the observed CAP1 -> Guest TIMG12 -> physical PWM chain.

## Follow-up verified negative control #40812856179

After this note was written, the same-source Motor Output=1
SIM_ONLY negative/positive control completed successfully:
[GitHub CI #40812856179](https://github.com/cctsao1008/escape32-qemu/actions/runs/40812856179).

At fixed ESCape32 source commit `907c5c3285ea1eebafe247c918c882609bf2db16`,
the **only** build-fixture difference was the presence or absence of
`AM13E_BEMF_INITIAL_DAC_CODE=2048`. Both received 3300 independent
QEMU Direct20 DShot frames. Passive read-only linked-SRAM markers
established:

| Setting | `motor_output_start_reject` | `runtime_fault_reason` | `fault_latched` | CI |
| --- | ---: | ---: | ---: | --- |
| No DAC seed | **3** (BEMF start reference not ready) | **6** (Motor Output Start rejected) | 1 | PASS expected fault |
| 2048 QEMU model seed | **0** | **0** | 0 | PASS expected start |

This **directly proves the nested reject predicate in the controlled
reproduction**, unlike the older failure artifact which only logged
outer fault reason 6. The old 2026-10-29 historical ELF did not itself
record nested reject=3; keep that provenance distinction.
This addresses the SIM_ONLY fixture fault, **not** a 12S hardware
calibration or permission to bypass the BEMF reference guard.
