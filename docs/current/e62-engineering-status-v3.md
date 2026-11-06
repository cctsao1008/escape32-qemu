# E62 execution — 2026-11-07 (Asia/Taipei), v3

Executable work completed since v2: exact Issue3 artifact recovery/SHA verification and14-case qualification; isolated changed-code SC5 handover with regression; new source chronology for signed reference offsets; corrected firmware PR bases. No production merge or issue closure.

| Acceptance criterion | Status | Result |
|---|---|---|
| #3 Recover exact5b90 ELF and supplied CFG | DONE | ELF5b90b200429333cef82b982b7a7f845f31fb885c7ea63fc7e783c75232fac8d1 verified; CFGab144c4b… provided by same archive. |
| #3 Exact14-case execution / all failure evidence | DONE | All14 executed against unchanged QEMU/scenarios/gates. |
| #3 Complete robustness qualification | FAILED | Seven experimental non-SHA passes, seven failures. All six nominal cases pass; stress failures remain. |
| #3 Source virtual-time gate | FAILED | One original-suite frame344ns late vs unchanged100ns budget; separate repeat passes, does not replace failure. |
| #4 Reproduce changed-code consumer liveness gap | DONE | SDK register reproduction retains old association despite valid changed-code producer, then safe-off at existing age limit. |
| #4 Isolated guarded changed-code publication sequencing | DONE | REGISTER_TESTED only: delayed active load, quarantine/filter/settling, freshness/epoch/mux/input/polarity, accepted timer and cancellation tests. |
| #4 Native changing-VBUS handover / settling sufficiency | IN_PROGRESS | Constant-VBUS motor scenario does not prove changed-code path coverage. Two explicit synthetic ZERO intervals are not board settling calibration. |
| #4 Candidate motor regression | FAILED | All14 native probes complete input; all strict verdicts FAIL. No unit PASS overrides these. |
| #5 First-start offset causal chronology | DONE | +16 direct20 sampled reversal precedes first CAP1; -16 reversal follows CAP1. Separate failure paths. |
| #5 Stable startup/restart qualification | FAILED | Existing counterexamples retained; new SC5 matrix also reverses. No speculative general startup fix promoted. |
| #10 Independent source clock correctness | FAILED | New532/492ns deadline violations occur before first positive demand even with pre-start synchronization. |
| #10 Historical full provenance / new task restoration | BLOCKED_EXTERNAL | Previous exact WSL CFG/build/launch omissions and genuinely fresh-task requirement remain open. |
| #6 Numerical vs measured model correlation | BLOCKED_EXTERNAL | Prior numerical results retained; physical transient/prop/uncertainty inputs still missing. |
| #8 Hardware / production release signoff | BLOCKED_EXTERNAL | No bench/board/thermal/thrust/independent protection measurements; porting_complete=false/hardware_qualified=false. |

## Exact Issue3 outcome

The user ZIP687d2a71… contains the exact filtered.elf,336-byte CFG and prior smoke/gentle logs. SHA checked before launch; no rebuilding or binary substitution. New14-case execution is separate from uploaded historical logs. QEMU remains6.2.0/pin44f28/SHA d5f4f510…; source filter contract3ea4e672; original05563 unchanged. Historical artifact run40865298408/artifact12894011805 is recorded; the new execution is Codex cloud, not an invented CI run.

Six nominal plus0:16 gentle pass the experimental non-SHA gates.0:16 direct20 has a source-clock failure despite zero reversals.16:0 direct20/steps,-16:0 direct20/ramp100 and16:20 direct20/ramp500 fail mechanical/feedback gates. Original identity rejection remains held for every case; no result qualifies Original P1.

0:16 direct20 frame549 is observed at549551492ns vs expected549551148ns. An identical-input independent repeat has max2ns dispatch error and passes non-SHA gates, but its source epoch/initial arming differ. The suite stays FAILED. Timer callback vs event-observation lateness is not distinguished by current logs. No host wall time is used for chronology, no bad sample is removed and no budget widened.

The new SC5 run also has source-clock failures at frame420(smoke),448(ramp100),584(16:0 steps), with532/532/492ns lateness and synchronized source epoch100ns. All occur in neutral before positive demand. Positive-demand commutation cannot explain that earlier failure; source event/timer scheduling and observation need independent causal evidence.

Detailed commands,14-case table, per-case hashes/source stress and prior-rotor/first-event evidence are on [exact qualification branch](https://github.com/cctsao1008/escape32-qemu/blob/experiment/e62-cmpss-cloud-matrix/docs/current/e62-issue3-exact-qualification-v2.md).

## Changed-code experiment and limits

Separate firmware branch `experiment/e62-sc5-changed-handover` is stacked on PR7. It takes only acquired/calibrated values, disarms capture before shadow-DAC update, waits for actual native load and explicit settling ZERO intervals, rejects stale/invalid/changed-again/epoch/mux/input/polarity failures and preserves CAP1/counter/TIMG12 state. Fresh producer samples cannot extend a stuck handover's original age deadline. No synthetic DAC production value, IRQ or BEMF event is introduced.

Baseline and candidate107-group/full SDK register regressions pass, including the reproduced baseline limitation and new negative cases. ARM candidate/default builds pass; the feature-off ELF has no changed-handover state. These are register/control sequencing results, not analog settling validation. The independent no-journal binary d7a44dcd… source759a558 runs all14 native inputs; strict motor results remain FAILED. The dynamic-input integration gate is still software work, not a hardware-only blocker. Actual settling/transfer qualification also needs physical data.

New source evidence further distinguishes offset failure paths: +16 direct20 reverses at+9.166192ms before CAP1+13.303392ms; -16 reverses at+10.241860ms after CAP1+4.335860ms. All direct20 comparisons have preceding sampled0RPM/-0.524rad with finite sample ages. First T12 programming can precede first CAP1; these independent first timestamps are not a falsely asserted capture scheduling chain. Bias/calibration, observability and control-policy attribution remain separate. The correct TRM(D+1) DAC conversion was retained; no one-code/model adjustment is made to force PASS.

Firmware code/report: [isolated changed handover](https://github.com/cctsao1008/ESCape32/tree/experiment/e62-sc5-changed-handover). Companion full counterexample matrix: [changed regression](https://github.com/cctsao1008/escape32-qemu/blob/experiment/e62-sc5-changed-regression/docs/current/e62-sc5-changed-regression-v1.md).

## Review inventory

Firmware default branch is `am13e-port-v2`, not main. User-confirmed Draft PR6 diagnostics and PR8 release gates use that base; PR7 remains stacked on PR6. New handover is separate and stacked on PR7's branch. Existing Draft PR11 remains the timeline evidence review. Updated machine-readable review inventory and prepared new PR bodies are retained under docs/review. No automatic merge/closure. No repeated broad audit or original functional T01 rerun was used in place of this executable work.

New firmware Draft PR creation was attempted after code and tests were complete. GitHub returned `Post "https://api.github.com/graphql": Forbidden`; the published isolated branch and prepared PR body remain reviewable. This is API/network access failure, not an approval rejection.19 relevant runner/strict/P1 tests pass; an initial command using a nonexistent test-module name is retained beside its corrected result.
