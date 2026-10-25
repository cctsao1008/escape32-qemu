# G13B7.1 Correctness / Oracle / Profiling / Native Gate

Purpose: finish four review workstreams **before** accepting a new version.

## Correctness changes

- On PWM DAC sync with identical active and shadow values, do **not**
  call the comparator evaluator: doing so resets a pending majority-filter
  timer and can suppress a legitimate CAP1. Changed values still evaluate.
- Publish the three simulator-only analogue phase values together then
  evaluate comparator **once** (atomic vector commit). Existing standalone
  simulator MMIO remains unchanged for historical tests. No CAP1/IRQ
  injection, no original Firmware modification.
- A read-only QEMU Stage observer latches six possible comparator
  MUX+polarity combinations and real phase-state transitions; this is
  hardware-route evidence, not a reconstructed Guest ISR trace.

## Oracle and evidence changes

- Historical full G13B7 T01 valid CRC feed / sent ratio ~96%;
  **90%** is an explicit engineering sampled regression floor,
  **not** a validated electrical BER requirement.
- For positive hold stages >=1s, all six observed phase/polarity states
  and >=6 transitions must be present in the simulator stage latch.
- Require differential phase PWM and no high/low overlap, rather than
  trusting a `pwm_observer_ready_sample` boolean from test fixtures.
- Stage Guest CRC sample-span ratio must be >=90%, retain throttle
  tolerance, stage coverage and all original CAP1/TIMG12 progression.
- Trace crossing->CAP1 adjacency and triplets must each cover >=90%
  of eligible events (allows preexisting unmatched edges, not proof of
  physical/ISR causality).
- Reconcile old per-WFI Stage fields as JSON **null** with a literal
  provenance marker, never contradictory false/zero values on PASS.
- ABI bumped to 4, simulator MMIO extended to +0x118, explicitly
  fail-closed on stale QEMU. Original ELF hash is unchanged.

## Profiling and performance

- `host_perf_profile`: QTest engine polling, Guest SRAM reads, PWM
  observer reads, poll sleeps, unattributed host time. These are
  measured wall-clock host regions, not Guest instruction durations.
- `simulator_workload_profile`: actual DShot/edge/DMA, BEMF callback,
  timer_mod, QEMU route-duplicate, analog vector commits/no-ops, CAP1
  and TIMER12 IRQ **event counts**. Never report event counts as CPU time.
- T02 host timeout auto scales with scenario duration (override allowed).
- Performance improvement is OPEN until repeated equal-environment runs
  are measured; this patch is primarily about **correctness**.

## Four-phase validation order (enforced in CI)

1. Compile Python and run negative + positive autonomous Host Oracle tests.
2. Build QEMU 6.2 pinned source with G13B7.1 model changes; verify pinned
   original ESCape32 Rel17.3 ELF hash.
3. Native 50-frame bounded smoke must be OPEN (not a fraudulent PASS).
4. Native full 11,000-frame T01 must PASS aggregate, strict sampled stages,
   neutral teardown, and zero stale Legacy booleans. CI uploads artifacts.

The workflow is
`.github/workflows/g13b7-correctness.yml` and runs on changes.
GitHub Actions ubuntu-24.04 measurements are **not directly comparable**
to the prior WSL-22.04 44.34s/47.14s wall time baselines. To measure
actual speedup, rerun G13B6 and B7.1 on the same machine using the
same `/usr/bin/time` invocation and at least three repetitions.

## Remaining limitations

The two-stage oracle checks sampled source-owned throttle, selected
original Guest counters and simulated hardware-route masks. It cannot
prove individual DShot frame decode, analog/motor physics, **six-step
ordering** (only six-state coverage), real TIMG12 Guest ISR entry timing,
or silicon electrical/thermal limits. A separate higher-frequency
deterministic step trace would be necessary for sequence-order proof.
