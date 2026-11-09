# E62 execution v7 — 2026-11-10 Asia/Taipei

This phase fixes two executable software defects, establishes isolated SIM_ONLY integration branches, and extends native startup/restart coverage. It does not resolve all E62 acceptance criteria or authorize production. The v6 ELF and all historical failures remain untouched.

## Implemented corrections

H13 reused forward phase history after an exactly centered/unknown phase sample. Such a sample can hide a change of direction or missed sectors. It also silently ignored contradictory phase data or timestamps carrying the same sample identity. Three new UNIT counterexamples fail against firmware28346d4 (assertion exit134) and pass after correction3c6264a80f6e8f00233b89d53d1f39032ee8706d. Exact duplicate replay remains idempotent. The conservative correction invalidates history and requires a new coherent forward sequence; it does not manufacture a phase bit or direction measurement. Test-only commit af7eb7c adds interruption after the first actual-Core capture, without changing runtime source or relabeling the tested ELF.

QEMU timeout-oracle CI could not import its verdict: an inherited literal backslash-n at line70 of `tools/e62_issue5_native_timeout_verdict.py` causes SyntaxError. The exact failed CI command reproduced locally. PR17 commit225d288 replaces that token with a parenthesized multiline expression; predicates, failure names and acceptance thresholds are unchanged. The35 tests in the failed job pass after the repair. Integration retains the repair as well as the original PR histories. This is a diagnostic tool failure, not a firmware or motor verdict.

## Native evidence and selection

New firmware ELF SHA256 `2c5d655b78af53049b73d87553429807cb867ec07985d4b3c76df9bb06c0fd6c` is built from3c6264a with the explicit `e62_sc5_coast_phase.cmake` profile. It is EXPERIMENTAL, not Original05563b69 or Production Root Fixes c49a7485. Build commands, compiler/SDK pins and flags are in `artifacts/e62-v7/coast-candidate.build-provenance.json`.

The restored QEMU executable remains SHA256 `6f99975e319ada16af98050c66b1ee39fef690d8dca16ec08a6c59560f7faef8`; it was not rebuilt or substituted. Its reported source identity remains the historical8178dd2 source-VBUS build with upstream44f28df, not the new diagnostic integration HEAD. CFG SHA256 remains `ab144c4b281ec53feb399b45c758b1de72b2c16f252e6ff64980f263b3a51702`. Native motor/analog constants and solver are unchanged. Only explicitly declared initial pose or source-owned invalid-acquisition input differs in the additional cases.

The three nominal coast cases were rerun because the critical acquisition-history dependency changed. These are impacted regressions, not reconfirmation of unchanged v6 PASS. Two new initial poses extend incomplete coverage. No T01, whole QEMU host audit, Issue3 matrix or general timing campaign was rerun. Native socket binding initially failed in the sandbox before motor execution; that preflight is BLOCKED_ENVIRONMENT, retained separately. Approved outer execution then ran the exact binaries. Build invocation from the firmware directory initially lacked the QEMU Python module; corrected invocation is recorded, without calling it a firmware build failure.

| New case | Prior sampled restart RPM / wrapped electrical degrees | Guest oldstep → selected sector | First / second CAP1 us | Result |
|---|---|---|---|---|
| −30°,300ms coast |5.879 /351.876 |5 →1 |1649 /2415 |PASS_NEW nominal independent gates |
| −30°,1500ms coast |2.817 /262.244 |3 →6 |3139 /1636 |PASS_NEW nominal independent gates |
| −30°,3000ms coast |0.682 /93.726 |6 →3 |2659 /1766 |PASS_NEW nominal independent gates |
| +30°,300ms coast |18.044 /36.368 |1 →2 |2300 /1926 |FAIL scenario; restart window positive, first demand fails |
| +150°,1500ms coast |7.474 /125.571 |1 →4 |3806 /1501 |FAIL scenario; restart window positive, first demand fails |

Each nominal restart has1498 positive samples spanning about1497ms, no significant reverse samples, and thousands of real CAP1 ACK/TIMG12 commutations. Each first reacquisition timer has native100MHz LOAD99: actual START-to-IRQ1000ns, measured error0, and no replacement before IRQ. IRQ-to-pad execution is separately retained; a1us timer is not a1us capture-to-pad guarantee. All source times are absolute virtual nanoseconds. Prior rotor sample ages are approximately648–650us, explicitly retained. Angles derive from integer-milliradian source payloads, not higher-resolution measurements or Guest feedback.

The +30° run has561 significant reverse samples during the first demand; +150° has558. Their restart windows have no significant reversals and1499/1498 positive samples, but the unchanged independent oracle correctly fails both complete scenarios because the first-start prerequisite fails. Their first significant reversals occur1.350208ms and2.349648ms after demand, before accepted feedback. The first PWM pair is still C_H/B_L. The actual initial rotor poses are not assumed equal to reset configuration: at +30° the prior demand sample is−3.721RPM /158.433° wrapped, while +150° is0RPM /150.000°. Boot/audio motion and sample age matter.

These additional failures reinforce the open-loop sector-alignment mechanism. They do not show a defect caused by later TIMG12 scheduling or SC5 expiry. At standstill equal phase voltages carry no rotor phase/direction information. A fixed guessed sector or arbitrary alignment/current pulse is not an evidence-backed general correction. A bounded, protected alignment or independent Guest-observable phase acquisition contract still requires development and validation; no such policy is invented here.

## Observability and safety limits

The new mathematical alias witness shows that successive unwrapped forward sector positions k and reverse positions−5k produce identical sampled six-sector patterns. It is explicitly a UNIT counterexample, never a native measurement or injected motor feedback. The1-LSB positive UNIT vectors can also be reproduced by bounded noise around a stationary midpoint when no independent uncertainty bound is known. Freshness and consistent phase ordering alone cannot prove physical direction. The new invalidation correction fixes a separate implementation defect and does not resolve that information limit.

Gate-off ADC EOC/read prefixes in the native logs independently reproduce the sampled coast sequence without using source rotor state. This proves what the native Guest consumed in these runs; it does not prove continuously quiet pads, physical offset/noise/bandwidth, anti-alias bounds or generic brake/audio eligibility. The source model's terminal voltage/phase ADC assumptions remain SIM_ONLY. Reverse pattern/static/missing/stale/gap/epoch/rail/equal/reference-polarity negatives pass in the affected planner/Core tests. Native reverse-wind coverage remains incomplete; the old offset-driven reverse refusals remain tied to their original ELF and input identities.

A new actual-Core timeout after the first capture requests shutdown without another timer. Native invalid-reference interruption now passes the negative fail-closed criterion, with reacquisition FAIL. Source first CAP1 is3303481792ns, its native1us timer IRQ3303486424ns, invalid VBUS ADC EOC3303499464ns, subsequent pair commit3303552888ns, and all pads off3303605364ns. Thus conversion-to-sampled-all-off is105900ns; no latency threshold is invented from that observation. The final passive reference is invalid despite retained sample age18/32ticks, so this is invalid-only-before-expiry isolation. One actual first capture is retained (3260us), no second capture is accepted, and no subsequent CAP1/TIMG12/PWM_PAIR/T12_START events occur through the recorded5100ms source horizon. Final clocked evaluator is stopped with pad mask0.

The1us timer had already fired before invalid EOC. A physical pair commit occurs after invalid EOC while the higher-priority path completes, before fail-closed shutdown. Publication of invalidity has no direct source timestamp in this trace. Therefore this result does not prove a still-pending1us timer was canceled, a maximum allowed acquisition-to-shutdown latency, continuously observed pads outside the bounded window, or physical analog protection. Those criteria remain INCOMPLETE. The event ordering and limitations are machine-readable in `artifacts/e62-v7/interruption-audit.json`; refusal is never successful reacquisition.

## SC5 stress and other issues

New read-only separation of the preserved v6 stress failures finds six negative-torque samples and a−175.901RPM sample at+9.353112ms before accepted feedback in the +16 case. The −16 case has one negative-torque sample in the scheduled wait and21 after physical pair change; its−125.300RPM sample at+10.356112ms is post-commutation. Switching-only first start has no significant reverse sample in the initial50ms, but the later restart refusal/qualification failure is retained. The original90° failure similarly reverses at+2.352408ms before accepted feedback. These are sampled source/model observations, not integrated torque impulses or continuous phase measurements. Missing Guest decision history is marked incomplete; read/ACK/timer-programmed chains are source-observed inferences, never fabricated decision records.

The signed offsets require distinct investigations of low-speed crossing bias and subsequent commutation. No evidence justifies replacing dynamic calibration with synthetic codes or changing a physical transfer function. No new SC5 firmware correction is claimed from these replay observations.

| Issue / acceptance gate | Status | Evidence / remaining work |
|---|---|---|
| #5 unknown/contradictory history authorization |PASS_NEW |Three reproduced counterexamples corrected; exact replay preserved |
| #5 impacted nominal300/1500/3000ms restart |PASS_NEW |New ELF, independent source/rotor gates; not Original qualification |
| #5 v6 nominal results |PASS_REUSED |Historicalf61c7e2c identity only; not transferred to new ELF |
| #5 arbitrary-pose First Startup /90° |FAIL |New+30/+150 failures and saved90 failure; pre-feedback mechanism |
| #5 phase/speed/alias/reverse/noise/brake/audio qualification |INCOMPLETE |Native coverage extended; information and eligibility bounds unresolved |
| #4 dynamic register handover / old fresh-invalid isolation |PASS_REUSED |Existing exact identities; not physical settling or new-ELF qualification |
| #4 ±16 and switching robustness |FAIL |Saved cases and new source replay; no one-cause assumption |
| #3 exact14-case matrix |FAIL |Exact5b90b200 ELF:7 non-SHA experimental passes,7 failures; full qualification failed. No rerun |
| #10 source deadline100ns |FAIL |Saved344–532ns failures retained. No causal timing correction/campaign |
| #6 existing numerical/model software checks |PASS_REUSED |Versioned v3/v5 evidence retained; no changed model or numerical gate rerun |
| #6 measured motor/propeller correlation |BLOCKED |Need measured phase R/L/BEMF, inertia/friction/load, torque/speed/thrust transients and uncertainty |
| #8 Boot/Flash host/build fixes |PASS_REUSED |Exact PR8 source and historical official SDK/image/negative checks; review still required |
| #8 image/update release policy gaps |BLOCKED |Full-image integrity/atomicity/rollback requirements/interfaces still undefined; do not invent guarantees |
| #8 hardware release/protection/thermal/current/thrust |BLOCKED |Physical measurements and board approval, never SIM_ONLY signoff |

## PR integration and review

Both repositories now have `integration/e62-sim-only-v7`. Firmware is H13 with separately retained H8/H9/H10 prerequisites and the narrow history correction. QEMU preserves merge commits for offline PR11/12 on the published17 stack;13→15→16→17 remain explicit runtime/observer dependencies. Optional polling14 is excluded. Cross-repository source/ELF/QEMU/SDK/CFG/scenario/input/test/acceptance pins are in `artifacts/e62-v7/compatibility.json`. No inference equates a freshly named source HEAD with the historical executable.

The inventory `docs/review/e62-pr-inventory-v7.json` contains21 open PRs, exact heads/bases, complete changed-file lists, scope, runtime/safety assessment, upstream/downstream links, overlap, tests/checks/review metadata and blockers. No approvals were present. READY_FOR_REVIEW is not READY_TO_MERGE. QEMU13 is not wholly default-off: its timer context patch executes even when logging is disabled. Failed Original-rotor CI and saved deadline failures are not explained away by mergeability. Firmware1 is superseded as a development baseline, with manual disposition recommended and its evidence branch preserved. Intermediate7 still provides prerequisites despite the continuity defect corrected by H9.

| Repository | PR | Classification | Dependencies | Validation | Recommended action |
|---|---|---|---|---|---|
| QEMU |11,12 |READY_FOR_REVIEW |Independent offline additions |Existing CI/evidence; new offline integration checks |Integrated only into SIM_ONLY; review separately |
| QEMU |13,15,16 |NOT_READY |13→15→16 |Failed strict CI;16 timeout import repaired downstream |Keep runtime stack isolated; satisfy timer/Original gates |
| QEMU |14 |NOT_READY |13 |Optional polling, no proven timing fix |Exclude from selected baseline |
| QEMU |17,18 |READY_FOR_REVIEW |16;18 also integrates11/12 |35 failed-job tests and38 offline impact tests pass locally |Review diagnostic changes; no production target |
| Firmware |6,8,10,14 |READY_FOR_REVIEW |6/8 independent;10 based on9;14 based on10 |Existing pinned evidence; CI/reviews limited |Independent review, no default merge |
| Firmware |3,7,9,11,12,13,15,16 |NOT_READY |Explicit experimental/prerequisite graph |Critical and native evidence incomplete |Keep separately reviewable in SIM_ONLY |
| Firmware |1 |SUPERSEDED |Historical startup experiment |Newer work retains failures and identities |Recommend manual disposition; retain branch |

No PR was marked READY_TO_MERGE, made non-Draft, retargeted to production, merged through GitHub or closed. Only authorized local SIM_ONLY integration merges were performed. Existing Draft PRs remain open; recommendations are not approvals.

## Commands and regression impact

```sh
source /workspace/setup-escape32/activate.sh
# In the firmware integration checkout: new focused counterexamples and impacted Core tests.
bash mcu/_support/AM13E/tools/run_coast_phase_uncertainty_regression.sh
bash mcu/_support/AM13E/tools/run_coast_phase_regression.sh
# New interruption case only, after its test-only addition.
bash mcu/_support/AM13E/tools/run_coast_phase_regression.sh interrupted
# Critical acquisition path changed: full official SDK host/register gates required.
AM13E_SDK_ROOT=/tmp/e62-issues/sdk bash mcu/_support/AM13E/tools/run_coast_phase_sdk_regression.sh full
# In QEMU integration: exact failed CI command, then integration-impacted offline modules.
python -m unittest -v tests/test_e62_issue5_timeout_oracle.py tests/test_e62_issue5_native_timeout_verdict.py tests/test_e62_issue5_cap1_timer_audit.py tests/test_e62_issue5_bemf_diag.py tests/test_e62_issue5_bemf_decision_verdict.py
python -m unittest tests.test_e62_acquisition_timeline tests.test_e62_lifecycle_alignment tests.test_e62_uploaded_trace_inventory tests.test_e62_exact_cmpss_suite tests.test_e62_coast_acquire_diag tests.test_e62_restart_adc_observability tests.test_e62_restart_seed_diag
```

The full critical firmware suite passes107 named groups. The narrower SC5 and actual-Core impact checks also pass. The unselected coast module preprocesses byte-identically to v6; enabling the observer without SIM_ONLY is rejected. This is module-level default equivalence, not proof of an unbuilt whole production ELF. No qualification is transferred across ELF hashes. Each native `*.command.json` contains exact argv and input identities; `run_v7_native.py` in the archive provides screen/remaining/interrupted selection and refuses existing output overwrite. The first run is serial, the remaining cases use two workers, and interruption is serial after they finish. Source virtual timestamps, not host concurrency or elapsed time, define chronology. Raw failures and failed preflights remain available.

Existing strict host CI failures were not all declared solved by local tests: GitHub job-log redirection to `productionresultssa10.blob.core.windows.net` was denied, so failure annotations and a local exact-command reproduction were used. The35-test fix result is local and deterministic; the latest remote CI observation is recorded separately in the PR inventory.

Reviewable Drafts: [Firmware16](https://github.com/cctsao1008/ESCape32/pull/16), [QEMU18](https://github.com/cctsao1008/escape32-qemu/pull/18), and updated [QEMU17](https://github.com/cctsao1008/escape32-qemu/pull/17). No production merge is proposed by this report. Remaining software gates include arbitrary-pose startup, physical-direction admission bounds, reverse wind and general owner eligibility, post-authorization stress coverage, target timing/interleavings and independent full qualification. Hardware is not the only remaining blocker.

Final branch tips are QEMU integration81de1446ff02f8b97b3e3f565c5ecb738aea9096, firmware integrationaf7eb7c410532e6ae39cb512cb83cd5abd38cfd2 and diagnostic PR17225d2886d7cf6268d3ff804831730326e1c1b368. GitHub confirms both new PRs OPEN/Draft. QEMU18 remote offline-diagnostics and pinned existing-firmware-reference-contract checks are green; no review approvals or firmware16 check-runs were reported. Runtime-subtree patch IDs independently match H9 PR11 to integrated3539a11 and H10 PR12 to integratedd5d416e; that equivalence does not establish ISR timing qualification. Remote default branches remain main3f1ed18e53e115d13b5bad2450d4e315a3d5cea0 and am13e-port-v253953c04f7d857f3b402b3a19870605ed0471d8f. No defaults or issue dispositions changed.

The exact Issue3 v2 qualification report/JSON is versioned on `experiment/e62-cmpss-cloud-matrix` and the new QEMU SIM_ONLY integration branch; it is not falsely claimed to have existed on the earlier report branch. A copy is included in the new evidence archive. Raw reused stress/90 failures, command provenance, the new exact ELF, source git bundles and hash manifests are also included. The required restored QEMU executable remains an explicitly pinned external runtime dependency of the archive, available in the published environment; no replacement binary is implied.
