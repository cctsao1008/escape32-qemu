# E62 engineering execution report — 2026-11-06, v1

The six issues are **not resolved**. A causal SC5 acquisition-liveness defect has an isolated, opt-in experimental fix; boot build/test gate defects and diagnostic defects have separate corrections. Original startup/restart motor qualification remains failed. Exact historical evidence, a genuinely fresh task, model measurements and board measurements remain unavailable. No issue is closed, no production change is merged, and no threshold or motor physics has been adjusted.

Machine-readable identities, exact per-run hashes and branch commits: `e62-engineering-evidence-v1.json`. Raw evidence paths below are relative to this checkout, retained outside Git. Status meanings: DONE = stated limited criterion demonstrated; FAILED = executed criterion does not pass; IN_PROGRESS = executable acceptance work unresolved; BLOCKED_EXTERNAL = required evidence/access unavailable. A diagnostic DONE never upgrades independent motor or hardware gates.

## Overall acceptance matrix

| Issue | Acceptance criterion | Status | Evidence / limitation |
|---|---|---|---|
| #10 | Verify restoration in a genuinely new published-environment task | BLOCKED_EXTERNAL | Same onboarding instance; no task-creation tool. This workspace cannot prove restoration. |
| #10 | Same-instance HEAD, submodule, binary hashes, host audit, full functional T01 + independent verifier | DONE | main 3f1ed18; QEMU44f28; original05563; 62 host tests + audit; 11,000 frames; functional-only PASS. |
| #10 | Source-owned absolute DShot anchors, boundary rotor samples/age, observed vs inferred states, audio vs six-step, missing/stale bounds | DONE | Extended PR11 timeline/alignment tools, 19 focused tests and real cloud replays; source SWITCH/audio intervals remain bounded. |
| #10 | Replay three specified synchronized WSL datasets with raw/scenario/CFG/provenance | BLOCKED_EXTERNAL | All three bundles unavailable; user will supply archive. New cloud cohort is a separate identity, not replacement evidence. |
| #4 | Calibration contract / conversions / coherent sample identity / epoch / stale handling | DONE | Existing source53953 contract reused; official SDK/host negative tests, no production midpoint seed. Actual board constants unavailable. |
| #4 | MCPWM publication, phase/polarity, CAP1 fail-closed negative tests | DONE | Native register suite verifies all phase/polarity mappings; missing/stale/invalid/phase mismatch/delayed active-DAC cases. |
| #4 | Investigate dynamic SC5 acquisition liveness | DONE | Baseline fault at age33 > unchanged32 despite newer valid sample; independent uninstrumented control zero captures. |
| #4 | Isolated equivalent-code liveness correction | DONE | Experimental sourcebb02, pinned no-reference-journal run132 captures/131 serviced; not production approval or motor stability. |
| #4 | Complete dynamic changed-code/bus-transient reference handover | IN_PROGRESS | Same-code fix does not implement changed-code settling/publication. Fail-closed is retained. |
| #4 | Rerun all nominal/offset motor regressions after experimental control change | DONE | All14 executed;11 non-SHA failures, two identity-only failures, one incomplete event-budget failure. Suite FAILED. Not Issue3 exact evidence. |
| #4 | Physical calibration / route / settling confirmation | BLOCKED_EXTERNAL | Board BOM/netlist, measured divider/reference/gain/offset and settling absent. |
| #5 | Demand-boundary actual rotor state / acquisition / timer evidence | DONE | Original A/A and SC5 runs; first-event, CAP1 read/ACK/TIMG and phase/torque analyzers reused. Gate freshness remains explicit. |
| #5 | First Startup / 300ms restart no significant reversals | FAILED | Original A/A: 262 reversals per demand; candidate full run also262 per demand. Capture counts do not imply lock. |
| #5 | Coast observability / near-stall reacquisition | FAILED | 100 source ADC triplets in final100ms before restart all rank ties, contrast <=3 codes; no valid phase-order observation. Safe refusal is not successful restart. |
| #5 | Earliest matched-run source divergence | DONE | Original A/A WWDT_FEED seq7409 differs32ns before first demand; new090 A/A ROTOR seq6971 differs224ns. Not a proven firmware fault. |
| #5 | Discriminate deterministic replay from independent-boot scheduling | DONE | Fixed debug transport/finalization;74,596 exact source events/4820 frames record/replay. Independent A/A nondeterminism attribution still limited. |
| #5 | Qualify near-stall, all coast300/1500/3000, second demand, both directions and invalid-signal cases | IN_PROGRESS | Existing archived failures preserved. No unsupported firmware startup fix promoted. Physical measurements are NOT a closure prerequisite for this SIM_ONLY issue. |
| #3 | Exact5b90 ELF recovery and independent SHA check | BLOCKED_EXTERNAL | API artifact12894011805 returns Forbidden; no binary downloaded. Source-built reproduction is a distinct ELF, never substituted. |
| #3 | Exact14-case nominal/stress qualification | BLOCKED_EXTERNAL | Guarded runner prepared, 14 cases marked unavailable/executed0. Existing verified +/-16 evidence reused; not blindly rerun. |
| #3 | Immutable Original/P1 guards and per-case evidence retention | DONE | Guard tests reject substitution; strict non-SHA thresholds unchanged; no suite PASS from launches/counts alone. |
| #6 | Source parameter provenance / numerical correctness / convergence | DONE | Existing source/datasheet audit reused;46 focused model tests; actual first90ms frozen-switch replay107 edges/90 rotor samples passes. |
| #6 | Traceable motor/prop/load/PSU uncertainties and measured transient correlation | BLOCKED_EXTERNAL | Physical RPM/V/I transient, calibrated sensors/time sync, intended prop curve/inertia/limits missing. Correlation tool rejects synthetic/unaligned input. |
| #6 | Qualified intended47V KV210 propeller scenarios | BLOCKED_EXTERNAL | Requires validated parameters and safety gates. New47V source diagnostics are not that qualification. |
| #8 | ARM boot/application/diagnostic compile + image audit | DONE | Isolated Boot case-label correction; official SDK; all listed targets/image audit pass. |
| #8 | Software programming/CFG/flash failure/retry / handoff tests | DONE | Isolated host link fix; actual BIN tested with ASan/UBSan;107 host groups;29 release/readiness Python tests. |
| #8 | Full-image integrity / atomic update / rollback guarantee | IN_PROGRESS | Adopted protocol lacks these guarantees; existing tests expose limitations. No invented interface or approval. Needs product policy/interface decision. |
| #8 | Physical bring-up, independent protections,47V45N/90N5s/current/thermal, signed release | BLOCKED_EXTERNAL | No board/programmer/bench data or signed configuration. porting_complete=false; hardware_qualified=false. |

## Environment verification and discrepancies

This remains instance `ccarenv_b64_Y2NhcmVudl9kZGY1ZTBiYTBmOTg4MTkxODM2OGU5OWU3ZWQ1NWNmMA`, observed spec revision1. It is not a new task. The installation script was not rerun as a substitute for restoration verification. Later independent firmware builds required user-local ARM GCC/newlib/CMake/SDK packages; those additions do not prove the published snapshot contains them. Source `/workspace/setup-escape32/activate.sh` for runtime library paths. The existing QEMU executable can fail to load libraries without that activation.

At baseline the branch was `work`, HEAD `3f1ed18e53e115d13b5bad2450d4e315a3d5cea0`; all new logical branches explicitly fork that main or their documented prerequisite. Verification commands:

```sh
git status --short --branch
git rev-parse HEAD
git submodule status qemu
source /workspace/setup-escape32/activate.sh
.build/qemu-src/build/qemu-system-arm --version
sha256sum .build/qemu-src/build/qemu-system-arm baseline/e62-g13b3/firmware/AM13E-rev17.3.elf
bash tools/ci/check_autonomous_host.sh
python3 tools/ci/audit_repository.py
python3 tools/ci/verify_t01.py artifacts/e62-t01-full.json --output artifacts/e62-t01-qualification.json
```

QEMU version6.2.0, submodule `44f28df24767cf9dca1ddc9b23157737c4cbb645`; executable SHA `d5f4f5102469bb6dc4012682f4d7101d01b7c26fe7c3b29cd01a8c685ba7b943`. Original ELF SHA `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`. Final repeat host suite:27+29+6=62 tests PASS, repository audit PASS. Full functional T01 retained at `artifacts/e62-t01-full.json`:11,000 frames, `PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL`. Independent verifier: `PASS_T01_STRICT_FUNCTIONAL_ONLY`, rotor_order OPEN_NOT_PROVEN, board/thermal NOT_QUALIFIED. This scripted-BEMF functional test is not the autonomous native-plant P1 gate or Issue5 approval.

Reproduction of that full functional test uses the existing original SIM_ONLY CFG and declarative plan (do not overwrite retained evidence):

```sh
python3 tests/functional_dshot_sitl.py --autonomous \
  --autonomous-telemetry-interval-ms 200 --autonomous-wall-timeout-s 900 \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-functional-cfg-flash.bin \
  --plan scenarios/e62-dshot-v1.json --id T01 --artifact artifacts/e62-t01-fresh-replay.json
```

The exact new-task verification must still be run without installation unless restoration fails. No capability here creates a fresh Codex task. Runtime network policy is enforced/restricted, excludes `api.github.com`, and has no runtime secrets configured. Git read/push works; API artifact download and PR operations are separately blocked. A future environment draft allowlist is not an applied runtime policy.

## Provenance inventory

| Identity | Availability | Permitted evidence use |
|---|---|---|
| Original Rel17.3, sourceb020467, ELF05563b69… | Exact ELF available; hash reverified | Original functional T01 and native A/A only. |
| Production Root Fixes ELF c49a7485af218966a2e3ec764de8d997d8ba478954dcad42b88c0c99e4f3c003 | Unavailable | Prior reports retain this identity; never called Original. |
| Issue3 filter source3ea4e672, required ELF5b90b200… | Exact artifact inaccessible | No exact suite executed. A local new-compiler rebuild is a different binary, not accepted. |
| Source53953c virtual-ramp timeline ELF72858cbf… | Available new build | Separate cloud030/090 cohort only, no historical WSL substitution. |
| SC5 baseline/iterations/final candidate | Distinct SHA per run, cataloged JSON | Isolated experiment. Pinned final sourcebb02/no-journal ELF1452b4ec…; no Original/Production claims. |
| Experimental QEMU repo204fe85a512fff9ea0cfdfe430a29132c52197c4 | Inspected and source-built separately | Existing read-only ADC/audio/phase/CAP/TIMG observers reused by parsers; selectable200MHz/47V support stays experimental. |
| Three specified WSL sync-angle sets | Raw events/scenario/CFG/provenance all unavailable here | BLOCKED_EXTERNAL for each required component. User-local path is not cloud evidence. |

The new cloud cohort includes source53953c ELF, new compiler, explicit20ms coast, new CFG and a separately built204fe85 QEMU. Every difference is recorded; it is neither a faithful reproduction nor a completion of the three historical WSL gate datasets. It showed real Boot Audio at11.382072–386.438928ms and637.005316–887.063788ms before demand1500ms. The -90 repeats enter first demand near -4.470RPM / wrapped86.205°, not a presumed stationary -90° rotor. Early audio switching can move a free rotor.

## Root causes and changes

**Reference acquisition (#4):** stage selects sample1487 at tick23792, then fail-closed at23825 because age33 exceeds unchanged32; latest sample1488 is valid. Active/expected code2047 derives from virtual conversion. Baseline without the new journal also faults with zero captures. Optional equivalent-code refresh associates the newer same-epoch sample only across native MCPWM ZERO, quarantines CAP1 until publication, and preserves accepted-crossing/TIMG12 state. The committed no-journal candidate accepts132 captures/131 serviced; full preceding candidate264 captures but still significant reversals. Changed-code settling and actual varying-bus calibration remain unimplemented. See firmware experimental report for the failed iterations and negative tests.

**Startup/restart (#5):** Original matched runs both reverse262 times per demand. Before second demand the sampled rotor is +16.366RPM at wrapped275.166°; first20ms has min -257.724RPM and torque -2.057414Nm. First new CAP1 ACK is +7.172372ms. SC5 candidate second demand begins at -22.313RPM /220.731°; first sampled torque is -0.020174Nm, first20ms min -357.582RPM/-2.446779Nm, first CAP1 ACK +8.103156ms. Sampled extrema do not establish exact first physical crossing or a firmware-only cause. Long-coast and47V archived counterexamples are already documented on main and were not erased or rerun without matched inputs. No new speculative startup firmware fix is promoted.

The passive coast ADC audit reports5088 coherent triplets overall but all100 triplets in the final100ms before restart are rank ties, contrast<=3 ADC codes. This is insufficient evidence for phase-order reacquisition; safe refusal is different from successful flying restart. No rotor angle is fed to firmware.

**Scheduling/debug infrastructure:** source A/A divergence occurs before demand. Optional QTest transport patch excludes only the debug socket from QEMU character replay; the default QEMU wrapper deadlocks pre-start reads. Correct QMP quit acknowledgement then fixes recording finalization. One valid record and replay produce byte-identical74,596 events (4820 DShot frames), including absolute virtual ns. The replay host probe still fails its final poll because QEMU exits at recorded end. Independent source comparator passes and retains that failure; it does not invent the missing host snapshot. This demonstrates reproducibility conditional on one recorded input history, not full independent-boot determinism or a causal scheduling verdict.

**Robustness (#3):** prior +/-16 experiments remain model-based stress evidence. No repeated exact matrix is claimed without exact5b90. Download attempt:

```sh
gh api repos/cctsao1008/escape32-qemu/actions/artifacts/12894011805/zip
```

returns `Get "https://api.github.com/repos/cctsao1008/escape32-qemu/actions/artifacts/12894011805/zip": Forbidden`. The web artifact URL returned404; this is not evidence of expiry or nonexistence. No SHA verification is possible until bytes are accessible. Exact suite checks5b90 and Original055 before any launch and preserves all14 case results.

**Model (#6):** existing current-continuous model and source parameter audits were reused. First90ms actual source replay107 switches/90 rotors gives max RPM error3.75e-12, angle error0.0004012244rad and current error0.0004990586A;1000→500ns difference0.0003220961 versus500→250ns0.0001575896. This frozen-switch numerical self-consistency is not physical validation, full lifecycle convergence or47Vprop correlation. New correlation input requires PHYSICAL_BENCH provenance, sensor calibration, aligned integer timestamps, uncertainties and motor/prop identity; missing/unaligned/synthetic measurements are rejected. No parameters were fitted to get a pass.

**Release (#8):** Boot CMD_SETWRP declaration after a case label fails GCC14 pedantic C; a compound statement corrects it without motor changes. Flash host test omitted production app_validity header/link inputs; corrected separately. ARM Boot/App and diagnostic targets, actual BIN/image audit and ASan/UBSan programming/CFG preservation/failure retry pass. The adopted interface does not ensure full-image CRC, atomic update or rollback: passing tests cannot confer those properties. Product interface/rollback policy and physical signed-off release gates remain open.

## Review units and commands

All code units have separate published branches, no automatic merge. PR11 is updated through its branch. Other Draft PR creation is blocked by GitHub API access; reviewable branch links/body files are prepared under `docs/review/`. Firmware candidate is stacked on the passive firmware diagnostics; SC5 regression is stacked on passive parser support. Experimental QEMU transport patch stays optional and separate.

| Repository | Branch | Change |
|---|---|---|
| escape32-qemu | diag/e62-reference-startup-evidence | PR11: read-only reference/CAP timeline, lifecycle/real replay alignment |
| escape32-qemu | diag/e62-sc5-source-observer | Opt-in passive SC5 journal decoder/probe |
| ESCape32 | diag/e62-sc5-acquisition | SIM_ONLY passive reference journal + virtual calibration profile |
| ESCape32 | experiment/e62-sc5-equivalent-refresh | Isolated causal acquisition correction + register regressions |
| escape32-qemu | experiment/e62-sc5-regression | Pinned new SC5 integration regression, never Issue3 substitution |
| escape32-qemu | experiment/e62-cmpss-cloud-matrix | Exact historical5b90 14-case orchestration and substitution guards |
| escape32-qemu | fix/e62-passive-trace-schema | Accept five source-owned passive event types; no gate changes |
| escape32-qemu | experiment/e62-qtest-record-replay | Debug transport/finalization fix + independent source replay verifier |
| escape32-qemu | diag/e62-model-correlation | Read-only measured-vs-SIM evidence correlation contract |
| ESCape32 | fix/e62-boot-release-gates | Boot C compliance / flash host link correction |
| escape32-qemu | report/e62-engineering-execution | Overall status, exact provenance, acceptance and review inventory |

Focused test commands are in each branch's versioned report. Additional regression commands executed:

```sh
PYTHONPATH=.:tests python3 -m unittest tests.test_e62_porting_readiness tests.test_firmware_release_l1 -v
# Firmware repository, official SDK enabled:
AM13E_SDK_ROOT=/tmp/e62-issues/sdk bash mcu/_support/AM13E/tools/run_host_regressions.sh full
AM13E_SDK_ROOT=/tmp/e62-issues/sdk bash mcu/_support/AM13E/tools/run_sc5_equivalent_refresh_regression.sh
BUILD_DIR=/tmp/e62-mission/flash-host bash mcu/_support/AM13E/tests/boot/run_am13e_flash_host_tests.sh
/tmp/e62-mission/flash-host/am13e_flash_transaction_test --flash-image /workspace/escape32-qemu/.build/mission-fw-release-fixed/AM13E-rev17.3.bin
```

Logs, ELF identities, failed iterations, source traces, manifests and command arrays are retained in the raw engineering bundle. Initial failed experiments (ELF PT_LOAD overlap, incomplete RR recording, candidate failures and API rejection) are retained as failures; they are never reinterpreted as qualification. The supported linker option `-Wl,-z,max-page-size=0x1000` was necessary for new-binutils ELF segment placement, not a simulator behavior change.

## Precise remaining inputs and next executable gates

Supply each WSL bundle with its full raw log, source scenario, CFG bytes, original manifest/source/compiler/QEMU/ELF hashes and run metadata. Supply the exact artifact filtered.elf and independently match5b90, or enable the actual runtime GitHub API policy/access; then execute the prepared exact14-case runner. A new task using the published environment must execute verification without installation first. Required physical evidence is a traceable RPM/voltage/current transient with timestamps and sensor calibration, actual motor/prop inertia/load curves and limits, board netlist/BOM/sense transfer and settling, and signed bring-up/bench/thermal/fault/programming evidence.

Software work is still not complete: dynamic changed-code SC5 handover, independent first-start/near-stall/restart qualification, exact robustness execution and adopted update-integrity policy remain unresolved. The separate SIM_ONLY startup issue cannot be declared externally blocked merely because physical measurements are absent. Do not close #3/#4/#5/#6/#8/#10 from unit tests or functional T01.

## Final SC5 regression outcome

The separate SC5 candidate matrix finished14/14 native inputs. Every strict verdict remains FAIL:11 non-SHA mechanical/feedback failures, two identity-only rejections and one event-budget/incomplete verdict. Nominal significant reversal counts: smoke0, gentle5, direct20262, steps257, ramp100186, ramp500144. Stress cases include insufficient closed-loop activity for both signed offset direct20 cases and absent comparator/filter transitions for -16:ramp100. Switching16:20 ramp500 has zero reversals but remains an experimental binary, not Original acceptance. No result is used to fill the exact Issue3 matrix.

Five direct20 nominal/stress datasets were independently replayed through PR11's hash-verified timeline/lifecycle tools, retaining rotor sample age and incomplete lifecycle/gate evidence. Bounded analog source stress diagnostics verify the configured sign/magnitude; raw emissions and limits are explicit. Versioned detailed table/JSON lives on `experiment/e62-sc5-regression`.

Actual Draft PR creation attempt using a prepared body returns `Post "https://api.github.com/graphql": Forbidden`. This is a runtime network/API blocker, not an automatic approval rejection. Published branches are reviewable; no new PR is claimed created. PR11 was updated by branch push.

A later environment restart retained the same instance ID, artifacts and branches. Readiness returned successfully; the API remained excluded at spec1. This persistence check does not satisfy the requested genuinely new published-environment task.
