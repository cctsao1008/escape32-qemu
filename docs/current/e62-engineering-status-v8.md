# E62 v8 — startup observability and pending-commutation admission

2026-11-10, Asia/Taipei. Continue from published v7; preserve its reports, binaries and failures. This phase resolves a software admission defect and establishes native pending-timer cancellation evidence. Arbitrary-pose First Startup remains FAILED. No production/default merge, issue closure, motor/analog model change or acceptance relaxation occurred.

## First Startup: causal evidence and limits

The preserved v7 −30° and +150° cases both have source samples reporting0.000RPM (not continuous standstill proof) and coherent, Guest-read phase triples[2048,2048,2048]. Their first powered pair is C_H/B_L. Initial source torque is respectively+0.031439Nm and−0.031431Nm. Thus identical passive phase evidence does not select a torque-positive initial sector at both positions. The +30° reset case is not actually stationary at demand: the prior source sample is−3.721RPM near158.43° wrapped, with Guest codes[2047,2047,2048]. Boot/audio motion is not a rotor-position measurement.

In the source model, with zero initial winding current and mechanical speed, phase BEMF is zero at every electrical angle. Its inductance is not position-dependent, so a stationary current response does not supply saliency position information either. For C+/B−, the model torque is proportional to sin(theta+120°)−sin(theta−120°), whose sign reverses for theta+180°. The recorded opposite torques are consistent with that model relation. Model angle and currents are used only in offline RCA, never fed to the Guest. This establishes a passive standstill observability limit; it does not prove that all excitation-based sensorless startup is impossible.

Negative torque/reversal in the +30/+150 v7 cases precedes accepted feedback. It therefore cannot be caused by a later accepted-capture timer. H13 is a coast-history observer, not a cold position detector, and retains its ambiguity invalidation unchanged. Fresh SC5 references do not resolve unknown rotor angle. The source ADC model's powered-phase BEMF publication is not a qualified physical terminal-voltage measurement; using those powered-phase values as an all-phase position oracle would not justify a physical firmware correction.

### Executable startup alternative: original sine mode

A controlled A/B uses the exact v7 ELF and unchanged motor/QEMU. Both runs start at configured+150° and drive the same source scenario:1500ms neutral,300ms4% demand,1500ms20%,300ms neutral. A uses the existing CFG with sine_range0; B changes only CFG byte25 to legal sine_range5. Original sine_power8, all calibration fields and the ELF remain unchanged. ARM compile-time offsetof assertions verify offsets25/26 and Cfg size332. The only additional observer difference is first-history readout after completion; active inputs differ only in the declared CFG field. Actual source states are measured, not asserted globally cycle-identical.

| Observation | A: sine off | B: sine range5 |
|---|---:|---:|
| First source torque Nm |−0.031361 |−0.132787 |
| Significant reverse samples in initial300ms |8 |6 |
| Significant reverse samples in300ms after first20% |0 |108 |
| First actual CAP1 virtual ns |1511622988 |1812879336 |
| CAP1 ACK / TIMG12 ACK totals |2734 /2734 |174 /1127 |
| Unchanged non-identity startup verdict |FAIL reversal |FAIL reversal |

B has no actual CAP1 during its initial sine interval, and reverses again around handover. Its open-loop TIMG12 activity is not successful BEMF synchronization. Neither configuration qualifies First Startup. The new CFG SHA256 is `a7c248a6f66b437efdf24276f20a8463db5f941cd7794e06d1c921416e6eaef2`; it is an explicitly labeled SIM_ONLY settings candidate, not production calibration or a replacement baseline.

Minimal alternatives remain: a protected excitation/alignment policy with defined current, motion, settling and handover bounds; independently measured saliency acquisition; or actual position sensors. A current-limited pulse/coast study is executable future software work, but its limits and acquisition conditions must be explicit rather than guessed from a passing pose. Position/saliency hardware evidence is unavailable. Safe refusal when phase information is insufficient is distinct from successful startup. No arbitrary fixed sector, hidden rotor input or unvalidated alignment pulse is introduced as a supposed fix.

## Pending timer: native proof and a separate admission defect

The v7 after-first-capture test interrupted after H13's1us timer had fired. New tests instead use the authentic +150° first accepted capture: Guest capture6648us, accepted delay2290us, native100MHz LOAD228999, START1506871180ns and deadline1509161180ns. No timer period is stretched for the test. A shortened, versioned first-demand scenario preserves the relevant original prefix and observes2100 source frames; it is a distinct fault-isolation scenario, not substituted startup qualification.

| v7 ELF fault input | Actual TIMG12 state at invalidity | Native result |
|---|---|---|
| source frame1507 |Stopped at1507604828ns with155635 counts remaining |PASS_NEW pending cancellation |
| source frame1508 |Stopped at1508604828ns with55635 counts remaining |PASS_NEW pending cancellation |
| source frame1509 |Deadline IRQ had already occurred |PASS_NEW timing negative control; cancellation not proven |

The reference journal's event5 records latest_valid0 while the retained association is still fresh at age18/32ticks. Its running ECAP timestamp is related to actual source CAP1/read timestamps with the pinned200MHz native counter; the analyzer retains a nominal±5ns mapping interval and verifies the local counter anchor. It does not map stopped post-shutdown counters as if they kept running. Remaining TIMG12 counts agree with the scheduled deadline within one100MHz peripheral tick. This counter consistency is an evidence check, not a relaxed P1 deadline.

For the early cases, invalidity is observed between the real accepted schedule and its unexpired deadline. The source STOP reports a running timer and positive remaining count. No later powered pair or timer event follows known invalidity; bounded SWITCH_FOCUS and the final clocked evaluator show safe-off. The derived invalidity-observation-to-all-off interval is1876–1886ns in those runs. These are measured bounds under the tested conditions, not a general hardware shutdown specification. Continuous pad safety outside the bounded source window remains unproven.

### Priority ordering and the firmware correction

Actual configured priorities are ECAP1=0, TIMG12=0, SysTick=0, ADC0/1/2=1 and PendSV=8 (four implemented priority bits). SysTick is not lower priority than TIMG12. Equal-priority active handlers do not preempt each other; PendSV can be preempted by either. When SysTick and TIMG12 are both pending, their architectural priority/tie ordering matters. The source native early-fault cases demonstrate the supervisor canceling in time.

A new actual-SDK/Core UNIT counterexample dispatches TIMG12 immediately after PendSV publishes reference_valid0, before another safety-supervisor delivery. The v7 handler consumes the timer and advances Core/stages another sector without revalidating the known-invalid reference. The corrected fixture reproduces this assertion failure on the unguarded path. This is a verified software ordering defect; an unwanted powered native pair in that exact preemption gap is **not** claimed as observed. Initial fixture setup failed before testing the hypothesis and is retained separately.

Firmware commit `aa67111194e47635ebc437fdc0cb40f159e68ab7` adds opt-in `AM13E_SIM_ONLY_SC5_COMMUTATION_ADMISSION`: before consuming a nonempty, armed TIMG12 event or calling Core, require an acquired fresh reference. Invalid/stale/blackout evidence enters the existing shutdown path. The guard requires an explicit SIM_ONLY calibrated profile. It changes no timer period, comparator/CAP1 event, P1 threshold, calibration value, producer cadence or motor physics. Empty vectors and canceled timers retain their existing handling.

New UNIT negatives exercise actual invalid ADC completion, overlapping CAP1 delivery, stale acquisition and blackout epoch change. They stop before a Core step and suppress late latched timer/CAP1 delivery after cancellation. A separate positive control verifies that an incomplete ADC epoch preserves the still-fresh prior reference, an empty IRQ does not consume the timer, and a valid expiry advances Core. These are manually dispatched UNIT flags, never native feedback. The exact rare PendSV/TIMG12 preemption gap remains unforced in native execution; target WCET and broader interleavings remain INCOMPLETE.

## New candidate validation and identities

| Identity | Value |
|---|---|
| v7 experimental ELF, fault controls and startup A/B |`2c5d655b78af53049b73d87553429807cb867ec07985d4b3c76df9bb06c0fd6c` |
| New admission candidate ELF |`7563267e0bafaf9b0321a1012736d880d4325c86de24750e5dba52afeb8be407` |
| Candidate runtime source/profile |aa671111… / e62_sc5_coast_phase_admission.cmake |
| Restored QEMU executable |`6f99975e319ada16af98050c66b1ee39fef690d8dca16ec08a6c59560f7faef8` |
| Normal CFG |`ab144c4b281ec53feb399b45c758b1de72b2c16f252e6ff64980f263b3a51702` |
| SDK |b872469ceef18de5e39a1d3acb0821ec158b44c7 |

Later firmware commits add tests only; they are not relabeled as the tested runtime commit or a new ELF. Original05563b69, historical Production Root Fixes c49a7485, exact Issue3 filtered5b90b200 and these experimental candidates remain separate. No QEMU rebuild or source/model substitution occurred. The executable's historical source provenance remains8178dd2/upstream44f28df, not the current diagnostic integration HEAD.

The new candidate passes all three impacted300/1500/3000ms independent restart gates. Each second demand has1498 samples≥50RPM spanning about1497ms, no significant reverse samples, and genuine CAP1/TIMG12 control. They were rerun because the IRQ admission path changed, not to reconfirm unchanged v7 PASS. All three strict P1 reports still fail Original Guest identity, correctly. Reacquisition after the deliberately invalid reference is not reported as successful startup or restart.

New candidate pending-frame1508 again cancels with55586 counts remaining and no subsequent powered pair. Its invalidity-to-sampled-all-off interval is1880–1890ns under the same nominal counter mapping. The frame1509 control again observes an already-fired timer. The native safety checks preserve behavior across the candidate change; they do not reproduce the exact UNIT preemption gap.

Critical-path changes required a full applicable SDK host/register regression:107 named groups pass. New focused negative/positive fixtures and the new eight-test read-only audit suite pass. The unselected timer translation unit preprocesses byte-identically to v7; enabling the new guard without SIM_ONLY is rejected. That proves module-level default equivalence, not an unbuilt whole production ELF. Original firmware and acceptance versions are unchanged. No T01, whole QEMU host audit, exact Issue3 matrix or broad clock campaign was run.

Ten native executions are preserved: three old-ELF fault controls, two old-ELF startup configuration candidates, and five new-ELF regression/fault cases. The complete failed startup and deliberate-fault P1 reports remain failures. All ten observed source dispatch maxima are0ns under the unchanged100ns criterion; this does not resolve or supersede the saved344–532ns failures.

## H13 uncertainty and other open issues

A new UBSan C witness calls the actual H13 planner with a coherent1-LSB history. The same sequence authorizes a sector under both forward-motion and hypothetical stationary one-code-noise interpretations. A modulo-sector reverse-alias witness is also retained. These are explicitly UNIT assumptions, not measured noise or actual native reverse trajectories. Calibrated amplitude/speed/bandwidth bounds could exclude some aliases; none are established by that witness. H13's ambiguous-history invalidation is unchanged, and its general physical direction qualification remains INCOMPLETE. No guessed production noise threshold is introduced.

The existing ±16 stress traces (v6 H13 ELFf61c7e2c, retained in the v7 replay; not Issue3 filtered5b90b200) now have additional geometric separation: +16's first accepted floating-A capture is bracketed by rotor−222 to−88RPM at54.7° to34.7°, away from a spatial A zero; −16's first accepted A capture is bracketed by+255.7 to+323.9RPM at10.6° to47.4°. Comparator threshold crossings under bias are not automatically geometric zero crossings or proof of synchronization. These sampled brackets do not interpolate an exact angle or prove a unique physical root cause. They explain why a known-invalid-reference guard cannot fix valid-but-biased low-speed feedback. Routing/publication/freshness checks remain separate from analog uncertainty and startup policy.

Issue3's exact5b90b20014-case evidence remains7 experimental non-SHA passes and7 failures, with overall qualification FAILED. No new-ELF result is transferred to it. Issue10's saved source-clock violations remain FAILED without a new discriminating scheduling hypothesis. Issue6's unchanged numerical software evidence is reused; physical motor/propeller correlation remains BLOCKED. Issue8's Boot/Flash evidence is reused while undefined image/update policy and physical production approval remain BLOCKED. Hardware is not the only remaining blocker.

## PR17 and PR18 reviewed separately

PR17 remains a diagnostics/orchestration delta above16. Review found a genuine evidence-loss risk: a failed attempt can leave command/QEMU logs without final JSON, while the old runner refused overwrite only when the final JSON existed. Commits2183fbb and7a38454 now reject any literal case-prefix output and atomically reserve both case and campaign index. Reservations survive failures; retries require a new output path. Six new tests cover partial logs, complete evidence, concurrent attempts, sticky reservations, distinct cases and literal bracketed names. No simulator or firmware behavior is changed. Its earlier timeout-syntax fix and35-test evidence are reused unchanged.

PR18 retains the new source-only fault scenarios, startup alternative inputs and offline pending-timer audit with eight new evidence-negative tests. It incorporates PR17's new commits with a non-production merge preserving history. Its delta changes no machine, timer implementation, analog transfer function or physics. Runtime observer ancestors13/15/16 are still not approved for default integration. A green diagnostic delta must not be used to merge those ancestors into production without their independent gates.

| Repository / PR | Readiness | Dependencies / recommendation |
|---|---|---|
| QEMU17 |READY_FOR_REVIEW |Base16; new partial-evidence safeguards separately reviewable; not production approval |
| QEMU18 |READY_FOR_REVIEW |Base17 plus existing offline11/12 integration; review new audit/source-input delta separately |
| Firmware16 |NOT_READY |Base15 with separate history correction and opt-in timer-admission commits; arbitrary startup, physical observability and target timing remain open |

Existing integration branches remain `integration/e62-sim-only-v7`; no redundant PR is created. All remain Draft. The full21-PR inventory from v7 is retained; only changed heads/diffs/readiness are refreshed in the v8 supplement. No issue or branch is deleted, closed or merged into a default branch.

## Reproduction

Activate the existing toolchain; no installation was rerun. Every native `.command.json` records full argv, source build, QEMU/ELF/CFG/scenario/input/test hashes and selection reason. Drivers are archived and refuse completed output paths. One inherited custom-driver selection description for the new candidate fault cases was generic; the companion selection notes correct its scope without overwriting the original command records.

```sh
source /workspace/setup-escape32/activate.sh
# Firmware integration: only the new ordering negatives.
E62_SC5_PENDING_ONLY=1 E62_SC5_TIMER_ADMISSION=1 AM13E_SDK_ROOT=/tmp/e62-issues/sdk bash mcu/_support/AM13E/tools/run_coast_phase_sdk_regression.sh sc5-only
# Only the new positive partial-ADC/empty-vector control.
E62_SC5_PENDING_ONLY=1 E62_SC5_PENDING_VALID_ONLY=1 E62_SC5_TIMER_ADMISSION=1 AM13E_SDK_ROOT=/tmp/e62-issues/sdk bash mcu/_support/AM13E/tools/run_coast_phase_sdk_regression.sh sc5-only
# Mandatory critical-path regression for the new guard.
E62_SC5_TIMER_ADMISSION=1 AM13E_SDK_ROOT=/tmp/e62-issues/sdk bash mcu/_support/AM13E/tools/run_coast_phase_sdk_regression.sh full
bash mcu/_support/AM13E/tools/run_coast_phase_ambiguity_witness.sh
# QEMU integration: new evidence tests only.
python -m unittest -v tests.test_e62_pending_timer_fault_audit
python -m unittest -v tests.test_e62_campaign_evidence_reservation
python -m tools.e62_pending_timer_fault_audit --events CASE.p0.events.log --evidence CASE.json --output NEW.audit.json
# Add --post-deadline-control only for the explicit after-expiry control.
```

The firmware profile, full source SHA, compiler14.2.1/hash and complete configure/build commands are in `artifacts/e62-v8/admission.build-provenance.json`. CFG provisioning includes the ARM ABI compile command and exact one-byte difference. The archive retains failed fixture setup, the pre-fix defect, negative analyzer fixtures and preflight corrections separately; they are not mislabeled as firmware/native motor failures. Future execution should use fresh output directories and exact recorded identities. No all-E62 completion, production qualification, physical direction-sensor claim or default merge is authorized by this report.

Final published heads: Firmware16 `bb8e4dc2eb3b1ecc5543cbe4adf2c96a45b83a03`, QEMU17 `464c1b3a5725baef267e7dd6cbdab0a76fd53fac`, QEMU18 `6b4e42a6f176ac099df671702b8056eec6c8519b`. GitHub confirms all OPEN/Draft. PR17 evidence-retention-unit is green; PR18 pending-timer-evidence-unit, offline-diagnostics and pinned-reference-contract checks are green. Firmware16 has no reported check-runs; its new local107-group critical suite is not relabeled remote CI. No independent review approvals were present. Remote defaults remain main3f1ed18e… and am13e-port-v253953c04….
