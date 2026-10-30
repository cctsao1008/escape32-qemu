# escape32-qemu — Single-main consolidation and safe branch retirement (2026-10-30)

## Purpose / scope

The **only long-lived branch after cleanup is `main`**. This document
records the source-branch tips, the **deliberately curated code** and the
reproducible SIM_ONLY qualification boundary. The user will remove all
six old branches **in one later operation**. Do not delete branches
as part of consolidation. The staging branch itself is temporary and
should be deleted when the user completes the one-time cleanup.

## Integrated *working-tree* scope

- Native QEMU opt-in `ecx87-kv147` and `ecx87-kv210` motor plants:
  phase R/L, terminal Kt/phase Ke, unchanged 24V model bus and
  current/rotor/three-phase BEMF coupling.
- Read-only QTest effective Kv/R/L/Kt/VBUS, checked against versioned
  `configs/e62-sim-profile-matrix-v1.json`; no name-only model.
- Independent OC-U/V/W 4095 ADC-like source fault calendar, Guest
  comparator/OST3 latch, six-pad safe off, retained after release, and
  no automatic rearm, with **Original Rel17.3 Guest**.
- Independent original nFAULT and WWDT input-loss regression.
- Independent second-demand and passive phase/BEMF analysis/oracles
  remain read-only **diagnostics**. Reacquisition is not qualified.
- CI workflows work from the `main` and transient integration branch.

## Excluded from mainline promotion / explicit known failures

- Experimental patched-Guest ival/4, 3ms BEMF startup and QEMU
  threshold/filter sweeps are **not** firmware production policy.
- Early BEMF robustness test run 41038956948 correctly FAILS with
  `STARTUP_SIGNIFICANT_DIRECTION_REVERSAL`; **do not waive it**.
- Actual 300ms coast successful second-demand handoff is not proven.
- The model's 1kHz `BEMF_FRONTEND` log is not the Guest ADC sample
  clock; a synthetic model cannot silently validate silicon signals.
- UV/OV/thermal source simulations remain NOT_MODELED (Issue #7).
- No real board measurements are needed for this SIM_ONLY scope.

## History-preservation method (important)

Simply documenting commit SHAs does NOT guarantee their continued
availability after remote branch deletion. Two baseline branch tips
are already reachable from `main`; the earlier `ival3000` tip is
reachable from the `quartergate` ancestry. The remaining three tips
(`quartergate`, `direct20`, `fix/g14`) require explicit reachable
history roots.

After curated code and integration CI have been verified, create a
**separate archive-only Git merge commit** whose first parent is the
curated integration branch head, additional parents are those three
legacy branch tips, and whose tree is **identical to the curated
integration tree**. This is an intentional `ours` historical merge:
the old commits are reachable but their unqualified experimental
working-tree changes are NOT imported. Clearly label it
`chore(history)` and do not misinterpret commit ancestry as functional
qualification.

When merged to `main`, independent compare checks must confirm all
six old branch tips are **ancestors of main** (ahead=0) before any
branch can be deleted. Record these branch SHA pins and relevant CI
in `docs/current/e62-branch-consolidation-manifest-20261030.json`.

## Release / deletion gate

1. Integration branch built from main; strict CI suite PASS with no
   changes to original P1 acceptance or the immutable Original ELF.
2. 6/6 OC source tests and nFAULT/WWDT original-Guest tests PASS on
   the curated integration branch.
3. Archive-only history merge preserves exact old SHA tips; compare
   each old branch against the integration head.
4. PR merged into `main`; re-confirm six tips reachable from main,
   check main CI and branch list. Only then mark **READY_TO_DELETE**.
5. User deletes six old branches plus the temporary integration branch
   in one separate step. This cleanup task does not delete them.
