# E62 execution v4 — 2026-11-06 UTC / 2026-11-07 Asia/Taipei

Native changing-VBUS integration now verifies two specific calibrated-reference handovers and safe shutdown under two source-owned sensor failures. Startup still fails with fresh matched reference observations. The saved344/492/532ns DShot violations remain FAILED:47 completed follow-up trials did not reproduce them. No acceptance threshold, production firmware, motor constant or issue disposition changed.

## Acceptance matrix

| Issue / acceptance criterion | Status | Evidence / remaining work |
|---|---|---|
| #10 Absolute source anchors, timestamp/sample-age preservation and bounded evidence | DONE | Existing tooling retained; new startup replay explicitly marks boundary instantaneous gates incomplete where SWITCH logs ended. |
| #10 Distinguish timer dispatch, callback, waveform and log observation | DONE | Separate opt-in source observer and guarded pinned-QEMU timer-context patch; offline decomposition tests. |
| #10 Resolve saved source-clock failures under original100ns gate | FAILED |47 completed follow-up trials, no recurrence; root cause remains IN_PROGRESS. Old failures are not superseded. |
| #10 Historical WSL full provenance / genuinely fresh published-task verification | BLOCKED_EXTERNAL | v3 omissions and fresh-task requirement unchanged; no claim that this resumed instance proves a new-task restore. |
| #4 Native sample→Guest read→calibrated changed code→shadow→active→ready | DONE | Two source input changes; exact completed ADC sample identities; phaseC/rising and phaseB/falling; capture quarantined; local ZERO/counter timing verified. Scope is these specific SIM_ONLY paths. |
| #4 Source-owned invalid/clock-loss safe shutdown | DONE | Invalid raw0 and missing EOC cases end with armed/published/ready0 and actual final gate mask0; original age32 retained. |
| #4 Invalid-only before expiry, all native phase/epoch/delay combinations | IN_PROGRESS | Native invalid-input observation also has stale previous reference. Existing isolated register negatives are not relabeled as native/hardware coverage. |
| #4 Actual analog settling / board calibration | BLOCKED_EXTERNAL | Explicit2ZERO fixture policy and affine virtual network are not physical measurements. |
| #5 Identify first-capture control decision with verified reference evidence | DONE | Passive persistent journal: first2782us capture rejected against5000us threshold; second13728us accepted, delay2733us. Source CAP1/read/ACK/T12 chain agrees. |
| #5 Stable first startup and flying restart | FAILED | Actual sampled reversal before first commutation with fresh matched reference observations; restart durations not exercised by the new short scenario. Prior failures remain. |
| #3 Exact14-case execution / robustness qualification | DONE / FAILED | User-confirmed Draft PR12; v3 exact5b90 results retained:7 non-SHA passes/7 failures. No rerun or binary substitution. |
| #6 Numerical work / physical model correlation | DONE / BLOCKED_EXTERNAL | Previously executed numerical gates retained; missing measured transient/propeller/uncertainty data unchanged. |
| #8 Executed software release gates / hardware production approval | DONE / BLOCKED_EXTERNAL | Firmware Draft PR8 retained; physical board, protection, thermal and thrust measurements still required. |
| #8 Full-image integrity / atomic update / rollback guarantee | IN_PROGRESS | Adopted programming protocol lacks these guarantees; product policy/interface decision still required. No claim of hardware-only remaining work. |

These are acceptance-criterion states, not six closed issues. Software gaps remain in timing RCA, native fault isolation and motor control; hardware is not the only blocker.

## Source-clock experiment and causal limits

Saved counterexamples, unchanged from v3:

| Guest | Case / frame | Expected source vns | Observed source vns | Error |
|---|---|---:|---:|---:|
| Exact5b90 |0:16 direct20 /549 |549551148 |549551492 |344ns |
| Changed-code d7a44dcd | smoke /420 |420000100 |420000632 |532ns |
| Changed-code d7a44dcd | ramp100 /448 |448000100 |448000632 |532ns |
| Changed-code d7a44dcd |16:0 steps /584 |584000100 |584000592 |492ns |

All have the original100ns gate. The latter three occur during neutral with source epoch100ns. Initial epoch synchronization alone cannot explain these later deadline discrepancies. A saved smoke failure has no runtime QTest request between pre-start source arming and the late event420ms later: contemporaneous host ADC polling is not required for that occurrence. Host scheduling, asynchronous clock advancement and earlier interaction remain hypotheses.

The observer saves QEMU timer expiry and timer-list dispatch snapshot before removal, then actual callback/wave/log clock reads and the actual first wire-edge callback. Context is thread-local and restored after nested callbacks. It never changes timer order, expiry or acceptance timestamps. Logging can perturb execution, so observer-enabled absence of failures is not proof that observation caused the historical failures. Baseline controls also failed to reproduce them.

| Follow-up factor set | Completed trials | Observed limits |
|---|---:|---|
| Exact5b90 serial sync/unsync, baseline, observer-disabled, concurrent4 |14 | No recurrence |
| d7a44dcd smoke/ramp/steps serial and concurrent4 |7 | No recurrence; early runs use default motor profile instead of explicit named-profile pre-start queries |
| Saved v3 SC5 argv replay: baseline4, observer4 |8 | Explicit named-profile arguments retained; no recurrence |
| Concurrent8: baseline8, observer8, both guest identities |16 | No recurrence |
| High-frequency1ms host polling |2 | One baseline serial and one observer run overlapping the VBUS campaign; not a matched isolated pair |

Across29 fully instrumented completed trials, post-first-frame source-event lateness is0–2ns; dispatch→callback→wave→log differences are0ns. First wire-edge lateness is≤2ns. These observations do not decompose a failure that did not recur. One earlier observer polling trial was interrupted by environment restart at995399208ns; its partial log and INCOMPLETE_ENVIRONMENT_RESTART marker remain. It is excluded from47 completed trials.

The baseline executable d5f4f510… remains preserved, including at the original build path. Observer executable d222ccc5… and dynamic-input executable6f99975e… are separate experimental identities. Build each review branch in its own generated QEMU worktree: the observer deliberately patches ignored util/qemu-timer.c, so reusing that directory across unrelated branches can retain diagnostic instrumentation. A compiler-only PASS does not qualify any of these builds.

Next timing gate: capture an actual >100ns recurrence with complete dispatch context (and, if needed, QEMU record/replay provenance) before choosing a correction. No timer change is justified by the present absence of recurrence.

## Dynamic native acquisition and publication

Versioned source plan `E62_SIM_VBUS_V1` changes external supply at DShot frame1840 to23V and frame1844 to24.5V. The prior input is integrated through the actual source timestamp before changing supply. Resistance, inductance, torque constant, inertia and integration equations are unchanged; varying the supply is the declared experimental input. With the plan disabled the legacy24V path is retained.

Native ADC1 SOC1/channel12 samples VBUS at the conversion request, completes through the existing native EOC/IRQ path, and keeps completed sample identity separate from the next pending request. Source-owned EOC/Guest-read/DAC-shadow/DAC-active events are sidebands, not fabricated feedback. A virtual affine network is declared explicitly: phase pin=1.41V+.02*(VBUS/2+BEMF), VBUS ratio11/160, ADC/DAC3.3V. At24V it preserves the prior1.65V center/.02BEMF gain. It is not a measurement or a production calibration.

| Actual completed ADC sample | Input / acquired raw | Independently converted DAC | Active native load | Phase / polarity | Software-ready observation* |
|---|---|---:|---:|---|---:|
|1829 |23V /1963 |2035 |1841530316ns |C / rising |1841698406ns |
|1833 |24.5V /2091 |2053 |1845531096ns |B / falling |1845699201ns |

*Values above are from retained bulk-v2 run. Ready times are mapped journal observations after publication, not invented exact flag-set times. Two ZERO events precede each observation. The actual5ns ECAP unit is independently derived/checked from local ZERO timestamp/counter pairs; an earlier mistaken20ns offline analysis is retained as incomplete and superseded only by explicitly labeled corrected replay. Both samples have ready-observation age19≤original32 ticks. Native source logs preserve acquisition/EOC/shadow/load timestamps and sample IDs. The code derives DAC values from calibrated samples; none of these observed codes is a production constant.

Journal request/load/ready chains429–432 and439–442 are individually complete. Earlier overwritten history stays missing. Capture is disabled at shadow and active load; selected mux/polarity, same blackout epoch, expected/active code, valid/fresh state and age are checked. The Guest ADC-read association is verified; host ADC1 RESULT access is treated as a confound. No source BEMF/CAP/IRQ/rotor event is synthesized.

Native negatives retain motor voltage24V while independently opening the virtual sensor (genuine raw0 EOC) or stopping the ADC conversion clock (pending conversion remains busy, no new EOC/IRQ; reset required for recovery). Both observed faults have old-reference age33>32 and post-shutdown armed/published/ready0 and actual final gate mask0. The invalid case also has latest_valid0, so invalid-only-before-expiry causality remains unproved. Wrong-phase/epoch, delayed-load, stale-ready, missing Guest-read, missing ZERO, active-code mismatch and host-result-access negatives are covered by register or offline tests, labeled accordingly.

The first word-by-word journal reader raced a live bounded ring; two positive probes are retained as incomplete failures. The corrected reader takes two unhalted SRAM block copies and keeps only identical committed records. It reports torn/missing sequences and growing heads, never fills them. Constant/up-down reruns and the versioned SHA-guarded campaign replay complete with the expected narrow verdicts. Neither wiring completion nor specific reference handovers imply rotor synchronization.

## Startup evidence after reference verification

The new experimental ELF e198f5e9… is built from e00c2ea plus an explicit virtual affine calibration profile, SDK b872469c…, ARM GCC14.2.1. It remains separate from Original05563, Production Root Fixes c49a, exact Issue3 experiment5b90 and no-journal candidate d7a44dcd. The c49 WSL evidence is not reused as if it came from this guest.

The constant-input passive-decision replay has source demand frame1500 at1500000100ns. The preceding measured rotor sample at1499349468ns is0RPM/−0.524rad, with sample age650632ns. Instantaneous gate state at that exact boundary is incomplete because the SWITCH log is bounded; the first subsequent physical six-step pair is recorded at1500301720ns, C-high/B-low, mask0x18. Boot Audio switching is not counted as this first-demand drive.

First CAP1 at1503001708ns is acknowledged/read, with no new T12 schedule before the next capture. The persistent firmware decision history directly reports capture2782us, interval10000us, threshold5000us, REJECTED_EARLY and delay0. Second CAP1 at1513947708ns records capture13728us and accepted delay2733us; actual T12_LOAD/START occur at1513948832/1513949016ns and commutation IRQ at1516682016ns. This corroborates the existing early-capture policy RCA with direct decisions, rather than repeating its source audit or mislabeling the gap as timer latency. Final rejected_events0 is not contradictory: that counter resets on capture start; the persistent first history retains the rejection.

At1509349468ns, before first commutation and before any VBUS step, measured rotor state is−175.984RPM, angle2.601rad, currents[0,−24.889,+24.889]A and torque−1.385192Nm. Counter-mapped reference observations at approximately1508484103 and1509484103ns (5ns counter resolution) bracket it: samples1496/1497, age16 ticks, expected=active2047, phaseA/rising, published/ready/armed/fresh/latest-valid all set. These are sampled observations, not continuous-state proof. They demonstrate that fixing reference handover alone does not resolve the first-sector reversal. Control-policy, virtual analog transfer and plant uncertainty remain distinct; no one-code DAC offset or early-capture threshold is changed to force green.

Flying restart after specified coast durations is not exercised by the short new scenario. Previous failure evidence and independent qualification gates remain. A safe startup-policy fix still requires matched A/B evidence for phase/sector alignment and actual torque/rotor synchronization, including failed early-acceptance experiments; capture-count improvement is insufficient.

## Reproduction and validation

Exact executed argv, input hashes, diagnostic environment flags and concurrency factors are retained per trial in the v4 bundle. The47 clock-trial manifests are the authoritative commands; early default-profile trials are not falsely labeled identical to saved v3 argv. Setup installation was not rerun. Environment restart interruption is preserved.

Build the experimental QEMU branch in an isolated checkout with its pinned submodule and `bash build.sh`. Build the firmware diagnostic branch with:

```sh
source /workspace/setup-escape32/activate.sh
cmake -S /workspace/ESCape32 -B .build/mission-fw-v4-vbus \
  -DESCAPE32_BUILD_AM13E=ON -DAM13E_MOTOR_RUNTIME_ENABLED=ON \
  -DAM13E_SDK_ROOT=/tmp/e62-issues/sdk \
  -DE62_QEMU_ROOT=/workspace/escape32-qemu \
  -DG13B2_SIM_ONLY_OPT_IN=ON -DG13B2_SIM_ONLY_IDEAL_BEMF_REFERENCE=OFF \
  -DAM13E_BOARD_BOARD_PROFILE_FILE=/workspace/ESCape32/mcu/_support/AM13E/cmake/test_profiles/e62_sc5_dynamic_affine.cmake
cmake --build .build/mission-fw-v4-vbus -j2
```

Recorded experimental ELF SHA256=e198f5e9f11fe9afaaddf8a169c8e30582382808c55c5336d60870777b7292d4; QEMU=6f99975e319ada16af98050c66b1ee39fef690d8dca16ec08a6c59560f7faef8. Rebuilds must record their own identity rather than claim byte identity without hashing. Actual replay command:

```sh
python3 tools/e62_run_vbus_campaign.py \
  --qemu artifacts/e62-v4/dynamic-vbus-qemu-system-arm \
  --qemu-sha256 6f99975e319ada16af98050c66b1ee39fef690d8dca16ec08a6c59560f7faef8 \
  --elf .build/mission-fw-v4-vbus/AM13E-rev17.3.elf \
  --elf-sha256 e198f5e9f11fe9afaaddf8a169c8e30582382808c55c5336d60870777b7292d4 \
  --firmware-source-commit e00c2ea \
  --cfg-flash artifacts/mission-sc5/sc5-g13b3-cfg-flash.bin \
  --case up-down --output-dir artifacts/e62-v4/vbus-campaign-replay
```

This exact wrapper run completed SPECIFIC_SOURCE_HANDOVERS_VERIFIED with no incomplete/failed case. Four underlying cases, the constant-input decision replay and the initial incomplete reader runs are separately preserved. `tools/e62_vbus_plan_smoke.py` passes11 paused-start cases, including valid plans and rejected bad version/initial frame/voltage/duplicates/range/sensor/trailing data/overflow. No Guest runs in those parser tests.

37 focused source-clock, bulk-journal, native handover negative, startup replay and existing strict/decision/CAP1-timer tests pass. The updated firmware full changed-handover SDK regression passes107 groups and production motor-register configurations. ARM ELF and both QEMU experimental builds link successfully. Complete commands and build/test output are archived; no claim that these replace Original P1 or physical qualification.

Review branches: QEMU `diag/e62-source-clock-observer`, optional `diag/e62-clock-poll-factor` stacked on it, and `experiment/e62-source-vbus-handover` stacked on the clock observer; firmware `diag/e62-dynamic-handover-evidence` stacked on PR9. Existing user-confirmed QEMU PR12 and firmware PR9 are recorded in the inventory. Production default firmware base remains am13e-port-v2. No branch was merged into production and no issue was closed.

Draft PR creation was attempted after publishing and validating the branches. GitHub returned `Post "https://api.github.com/graphql": Forbidden`. The four new branches, prepared Draft descriptions and compare links remain available for review; no new PR number is invented. This is an API access failure, not an automatic approval-review rejection.

Evidence archive: `artifacts/e62-execution-v4-evidence.tar.gz` (69,297,944 bytes), SHA256 `c8a5c2410a27cce79353aae9812a3d222b2bd57451d51b7bab1613d489065df5`. All455 archived manifest entries were independently rehashed from the completed tar stream. Three QEMU executables remain locally preserved and are deliberately excluded; their hashes, source bundles and build logs are included. Bundle details: [e62-execution-v4-bundle.json](e62-execution-v4-bundle.json).
