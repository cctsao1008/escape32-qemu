# E62 Integrated Validation Campaign — 10 independent objectives

This program **does not redefine** the G13B7.1 T01 acceptance baseline,
alter the original ESCape32 Rel17.3 ELF, waive rotor reversal, or claim
physical board safety from SIM_ONLY simulation.

## Test status and evidence requirements

| Objective | Evidence path | Accepted scope |
|---|---|---|
| 1. T02 (110s) | `e62-t02-functional.yml`, `verify_t02.py` | Functional SIM_ONLY only; 110k DShot600, 11 Stage checkpoints, native Guest CRC/ECAP/TIMG12, teardown |
| 2. Transitions | `tools/sitl_stage_oracle.py` | 500ms bounded stage transition settle, steady command tolerance; neutral PWM must not be differential |
| 3. Oracle hardening | Same stage oracle, independent T02 validator and negative fixtures | CRC progression/ratio, original Guest throttle, modeled PWM and phase-state coverage |
| 4. Source six-step | `tools/native_closed_loop_audit.py`, `tools/sitl_sequence_audit.py` | Pinned `(5,3,6,1,7,2)` original selected-code mapping; asynchronous samples **do not** prove complete order |
| 5. BEMF/CAP1/TIMG12 timing | QEMU temporal pairs + native Guest captured/scheduled/serviced counters | Temporal adjacency and monotonic progress only. ISR entry timestamps/complete causal graph **OPEN** |
| 6. Fault protection | `e62-safety-negative.yml` | Independent modeled external OC-U/V/W and nFAULT, actual Trip + original Guest fault ISR; any failure remains FAIL |
| 7. 12-sector G13B3M | `e62-rotor-strict.yml` | Independent native 12-sector / >=90ms and energy/rotor-direction gate; historically FAIL; never inferred from T02 |
| 8. Rotor/motor physics | `e62-physics-host.yml` | Current-continuous physical *model* equations (host only). Guest-coupled closed-loop + calibration **OPEN** |
| 9. Performance | `e62-t01-repeatability.yml`, `benchmark_autonomous.py` | At least three T01 runs same host, each Functional PASS; performance A/B with G13B6 **OPEN** |
| 10. Release traceability | `qualification_matrix.py` | Aggregate evidence with individual FAIL/OPEN; no production qualification without physical hardware |

## T02 independently observed baseline

Original G13B7.1 functional T02 (CI Run #40192829449 on initial
integration commit) completed 110s QEMU virtual time, 110,000 physical
DShot600 frames, all 11 full Stage checkpoints, original Guest CRC delta
105,574, CAP1 delta 91,803, TIMG12 service delta 91,787,
`PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL`, 0 issues, original source
Zero-DShot teardown PASS, on GitHub Actions Ubuntu 24.04. Its
wall time 514.63s is **not** directly comparable to a different host.

The subsequent transition/sequence instrumentation is a *new code
revision*, requiring its own T01/T02 regression. Do not transplant
the earlier result to untested new code.

## Boundary conditions and blockers

- A sampled code/step pair is not a chronological transition stream.
  Causal ISR ordering requires timestamps from original Guest software,
  or deterministic QEMU peripheral event sequencing with source-owned
  IRQ/ISR state evidence; sparse QTest reads cannot substitute.
- The existing `CurrentContinuousBLDC` requires explicit instantaneous
  H/L/Z gate states and reciprocal Ke/Kt. A 200ms averaged PWM duty
  cannot be used as such a switching waveform; doing so fabricates
  inductive current behavior. Motor Ke/Kt, resistance, inductance,
  inertia, propeller load and initial conditions remain uncalibrated.
- Historical G13B3M strict rotor reversal is a known failure, not an
  accepted quirk. Existing pinned binary checks may also fail when
  the pinned G13B3 QEMU SHA does not match newer Machine source;
  the **source-built independent** strict workflow does not silently
  republish or overwrite the original historic pinned pair.
- The negative safety tests use SIM_ONLY current/nFAULT stimulus.
  Physical Si/GaN gate drivers, PCB parasitics, current/thermal limits,
  ESC manufacturing and flight tests require a different HIL/bench gate.
- Continuous Guest sampling and Host scheduling produce different
  wall times on different CI/WSL machines. Performance requires
  paired same-host repeated runs. Do not optimize simulator timings
  until all functional tests pass.
- `qualification_matrix.py` is intentionally not a production-release
  green gate. A functional T02 PASS does not prove safe motor operation.

## Reproduce host tests

```bash
bash tools/ci/check_autonomous_host.sh
python3 -m unittest discover -s tests -p 'test_t02_*.py' -v
python3 tools/ci/qualification_matrix.py --output artifacts/e62-qualification-matrix.json
```
