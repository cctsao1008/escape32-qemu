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

## Verified integrated results (October 25, 2026)

**Full Strict Functional T02:** [CI #40194013746](https://github.com/cctsao1008/escape32-qemu/actions/runs/40194013746).
PASS 110,000 physical simulated DShot600 frames, 110s virtual, 11/11
Stage Gates (including 0% neutral and post-transition settled throttle),
CRC delta 105,578, CAP1 delta 91,809, TIMG12 service delta 91,794,
original source neutral teardown and zero oracle issues.

**Functional T01:** [CI #40194013528](https://github.com/cctsao1008/escape32-qemu/actions/runs/40194013528) PASS.
The final code includes extra read-only original Guest sampled Step +
selected comparator code evidence. The new `sampled_source_sequence_audit`
remains intentionally OPEN for complete chronological order; it cannot
turn 200ms QTest snapshots into all sector events.

**Negative protection:** [CI #40194013605](https://github.com/cctsao1008/escape32-qemu/actions/runs/40194013605)
PASS each nFAULT and OC-U/V/W genuine QEMU Trip and original MCU
IPSR=44 fault ISR -> source shutdown. **NOT_NATIVE_MOTOR_START**;
loss-of-signal reset/recovery is an independent OPEN path. Physical
DShot bad-CRC rejection is separately qualified below.

**Rotor strict failure:** [CI #40194013602](https://github.com/cctsao1008/escape32-qemu/actions/runs/40194013602)
red, despite 12 powered original Guest commutations: 20 significant SIM_ONLY
rotor direction reversals. Legacy host physics has nonreciprocal Ke/Kt
power ratio 7, and resets current at every commutation. A separate
Reciprocal Ke/Kt A/B [CI #40194544653](https://github.com/cctsao1008/escape32-qemu/actions/runs/40194544653)
also does **not** resolve qualification: the analog frontend exceeds
the test fixture voltage range as synthetic rotor speeds exceed ~7189 RPM.
Do not clamp this event to manufacture a PASS. Actual current-continuous
switching model tests are HOST_ONLY and are not yet linked to original
Guest PWM edges / comparator feedback.

**Performance:** [CI #40194013587](https://github.com/cctsao1008/escape32-qemu/actions/runs/40194013587):
three full T01 repeat trials all Functional PASS, wall times
60.929, 61.527, 60.425 s on one Ubuntu-24.04 Runner,
mean 60.960 s, sample standard deviation 0.552 s.
No same-host G13B6 comparator available, so speedup is still OPEN.

**Automated qualification report:** `tools/ci/qualification_matrix.py`
accepts T01/T02, rotor, source-native safety and coupled physics evidence,
and preserves independent status. It never emits "production qualified".
Current per-case safety report comes from
`tools/ci/safety_qualification.py`; model behavior tests alone do not
generate a system-safety release claim.

**Physical DShot CRC / source Watchdog feeding:**
[CI #40197254560](https://github.com/cctsao1008/escape32-qemu/actions/runs/40197254560)
PASS positive and negative original-Guest PA26→TIMG4 capture→DMA→
`am13e_app_io_dshot_packet` callback. Valid DShot value 1000 yields
callback return=1, original throttle 0→953, original WWDT valid-feed
counter delta=1. Flipping exactly **one CRC bit on the physical PA26
wire** yields callback return=0, throttle remains 0, original WWDT
valid-feed counter delta=0. In both scenarios original PB13 Gate
output remains LOW / inactive. This **does not** show the gate route
was physically disconnected; it is a *connected but neutral*
SIM_ONLY board profile.

Independent paired-artifact validator:
`tools/ci/dshot_crc_qualification.py` checks source return values,
wire checksum and data identity, physical 32-edge capture/DMA,
Guest throttle response, Gate inactivity and true WWDT source feed
delta. The CPU’s **actual expiration→BOOTRST→motor gate safe-off**
on input loss is still OPEN because the current QEMU WWDT model
does not implement full reset/shutdown propagation.

## Historical G13B3 archive integrity

`e62-pinned-archive-integrity.yml` checks the original **committed**
ELF/QEMU/libfdt bytes, sizes, `manifest.json`, and `SHA256SUMS`.
Published-release SHA256 and byte sizes for all three artifacts are also
independently pinned in code, so synchronized binary + manifest + checksum
ledger rewrites fail closed. It reports `current_source_drift_files` separately. A successful
`PASS_HISTORICAL_BYTES_INTEGRITY_ONLY` proves only the historical
archive has not changed relative to its manifest. It does **not**
requalify those 2026-October G13B3 QEMU bytes against changed current
Machine source and does not satisfy original G13B3L/G13B3M native gates.

The original `tools/e62_pinned_baseline.py verify --smoke-qemu`
continues to FAIL when source fingerprints differ, by design.
No hashes, binaries, source fingerprints or Strict Gate thresholds were
modified to make this separate integrity audit pass.
