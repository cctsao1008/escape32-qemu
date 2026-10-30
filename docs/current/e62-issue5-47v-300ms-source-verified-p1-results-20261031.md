# E62 Issue #5 — Four 47 V Original Guest 300 ms P1 Results (2026-10-31)

**Result: 4/4 SIM_ONLY FAIL, genuine source-backed `STARTUP_SIGNIFICANT_DIRECTION_REVERSAL`.** This is an **experimental profile** study, not real-board qualification and **not proof of a Firmware defect**.

## Reproducible provenance

- CI: [GitHub Actions #41110182593](https://github.com/cctsao1008/escape32-qemu/actions/runs/41110182593), source head `463febcb0e90abae7361585173ea1e5d027b477c`.
- Firmware: unchanged pinned Original ESCape32 Rel17.3 ELF SHA-256 `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`. No firmware edit, host Guest-register writes, WFI/GDB intervention, synthetic CAP1, or model rotor-angle injection.
- Source DShot scenario: `scenarios/e62-experimental-two-demand-coast-short300.json`, **5,100 source frames**, 1kHz PA26 DShot600, stages `1500ms neutral -> 1500ms +20% -> 300ms neutral -> 1500ms +20% -> 300ms neutral`, no Guest readiness gating.
- All four CI QEMU jobs: source build **PASS**, exact effective motor/voltage/APC/inertia readback **PASS**, actual Original Guest execution **PASS as a wiring/source smoke only**; strict Original P1 **FAIL** because significant rotor direction reversals persist.
- Initial electrical angle -30° is a machine-test independent variable, not Guest rotor position feedback. Changing physical model parameters changes the simulation, **not the acceptance gate**.
- GitHub Actions artifact names are `e62-case-<profile-id>-300-SIM-ONLY` in the linked run; they contain raw `*.p0.events.log`, `*.qemu.log`, run JSON, profile readback, and `*-strict-original-p1.json`.

## P1 source results: all four FAIL under identical Original Guest + scenario

The exact below counts and RPM extrema come from `tools/native_p1_qualification.py` in workflow **#41110182593**; the source is QEMU motor `ROTOR` events, not a user-supplied speed simulation.

| Exact case ID | 1st +20% demand: sign changes | 2nd +20% demand: sign changes | First demand RPM min/max | Second demand RPM min/max | Original P1 |
|---|---:|---:|---:|---:|---|
| `CTL-KV210-47V-NOPROP` | 421 | 422 | -529.536 / +619.310 | -512.569 / +556.328 | **FAIL** |
| `QB-KV210-47V-APC24X12E-J1` | 420 | 421 | -523.866 / +616.346 | -677.752 / +559.143 | **FAIL** |
| `QB-KV210-47V-APC24X12E-J2` | 297 | 297 | -398.015 / +460.368 | -398.486 / +500.601 | **FAIL** |
| `QB-KV210-47V-APC24X12E-J5` | 185 | 187 | -279.701 / +341.667 | -323.801 / +412.039 | **FAIL** |

The significance threshold is the **existing** P1 threshold: RPM magnitudes of at least 50 with successive opposite signed observations. **Counts are diagnostic, not speed/propeller/restart qualification**; lower count in J5 does NOT mean restart works or that its unknown inertia assumption is correct.

All four original P1 failure lists consist of `STARTUP_SIGNIFICANT_DIRECTION_REVERSAL`; the strict parser now accepts only two newly emitted *authentic* QEMU source kinds `ADC_PHASE_EOC` and `ADC_PHASE_READ`, alongside the existing grammar. Unknown source kinds, clock reversal and noncontiguous source event sequence remain fail-closed. No control timing or acceptance criterion changed.

## Previous source-artifact independent cross-check (not the same run)

Prior [#41109233164](https://github.com/cctsao1008/escape32-qemu/actions/runs/41109233164) had a **trace-parser compatibility failure** after completing identical 5,100-frame source runs. Its full QEMU artifact files were independently inspected with a six-field event-format parser, requiring contiguous source event `seq` and nondecreasing `vns` (zero missing/malformed records, 68,403–70,911 records depending on model). The positive stages had clear forward and backward RPM excursions. Native motor status reported zero model faults and zero OST3 latches; each actual Guest ADC phase had around 5,090 ADCRESULT reads. At the first 20ms of the second positive demand, minimum **model-only electromagnetic torque** was around -1.49…-6.75 N·m in those previous runs (not measurements).

These two CI runs should not be merged into a single deterministic trajectory: phase onset/callback scheduling and the starting rotor state can differ between runs, and the exact min/max RPM change. **Reproducibility is a separate QEMU/source timing concern**. Still, both independent runs show early bidirectional RPM under positive commands; adding realistic-load *assumptions* did not resolve the original sensorless startup problem.

## Engineering implications and required independent next checks

1. **Keep Issue #5 OPEN.** First demand itself fails the unchanged direction-sign gate in every studied 47 V profile. The issue is not isolated to 300ms windmill re-acquisition.
2. The *47 V no-prop control* also fails, so the APC aerodynamic torque assumption alone is **not sufficient** to explain it. This does not isolate QEMU versus firmware without a same-source-commit 24 V KV210 control.
3. Acquire **both unchanged 24 V baseline profiles in the same QEMU/Original Guest build and same DShot scenarios**, and compare output while holding motor, source, initial phase, voltage or load constant as appropriate.
4. Independently verify QEMU MCPWM pad-to-phase mapping, six-step sequence, rotor direction/angle convention, BEMF phase reference, CMPSS CAP1 and TIMG12 IRQ path, switch-current continuity, and analog/current-source model. The observed six source power-pair sequence in the first positive demand is `8 -> 2 -> 3 -> 6 -> 4 -> 7 -> 8`; this is a QEMU source observation, not proof that the physical phase wiring is correct.
5. The modeled phase-current peaks from prior #411092 artifacts were about 196–200 A. **Do not equate instantaneous simulated per-phase current to the customer's peak/continuous current definitions** without matching measurement convention; it is a model calibration/driver-limits concern and no product current qualification can be claimed.
6. Propeller J1/J2/J5 and reverse aerodynamic drag remain *assumed*, not manufacturer-measured. Correct or calibrate QEMU models only with a physically supported explanation, never for a green P1.
7. Firmware remains unchanged except for an independently demonstrated actual Firmware Bug. **A failed QEMU simulation is not independent proof of a Firmware Bug.**

**Status:** source-backed SIM_ONLY restart FAIL (all four 47V cases), not hardware-qualified; Issue #7's separate limited protection qualification is not reopened.
