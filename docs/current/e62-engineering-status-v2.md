# E62 execution update — 2026-11-07 (Asia/Taipei)

The Issue10 historical raw traces are now available and replayed. This supersedes their raw-log-unavailable status in the v1 report. All other v1 engineering results and unresolved software/hardware gates remain unchanged. No issue is closed or production change merged.

The user archive SHA256 is `7fe331fc3ede1290cc63afc00db217baa37b041a0868e9918e77eefd7c2ad8ea`. It contains eight runs, including all three required datasets. All eight pass internal source-sequence/count/DShot checks and agreement between raw events, full QEMU logs, JSON sidecars and final stdout. Their declared firmware is **Production Root Fixes c49a7485**, never Original05563 or Issue3 filter5b90.

| Criterion | Status | Evidence / remaining gap |
|---|---|---|
| #10 Required historical raw streams + runtime summaries | DONE | Three required sets received; five additional repeats also analyzed. |
| #10 Actual source timing and sampled boundary rotor replay | DONE | All4820 DShot frames per run validated; absolute timestamps and sample ages retained. |
| #10 Standalone scenario, CFG, guest/QEMU build identities, launch configuration | BLOCKED_EXTERNAL | Archive omits these bytes/manifests. Declared scenario SHA is not independently verified. |
| #10 Private lifecycle / full gate / reference publication identity | IN_PROGRESS | Audio-clock ownership remains inferred; bounded SWITCH/ROTOR/journal evidence remains incomplete. |
| #5 Historical restart boundary motor-state evidence | DONE | Before second demand:+2292.744RPM(-30r1),+933.714RPM(-90r1),-262.103RPM(-90r2). |
| #5 Matched-provenance repeat attribution | BLOCKED_EXTERNAL | Same reported settings but missing CFG and build identities. Earliest -90 source mismatch428ns before first demand is not a causal verdict. |
| #5 Stable startup / autonomous restart qualification | FAILED | -90 first-start traces already contain significant reverse samples; second restart02 begins rotating backward. No strict PASS granted. |

The real scenario is1500ms neutral /1500ms20% /20ms neutral /1500ms20% /300ms neutral. A legacy default `coast_ms=200` JSON field is not the executed stage plan. Source anchors remain100,1500000100,3000000100,3020000100,4520000100ns. A neutral command does not mean a stationary rotor. Stale gate samples are not carried forward as boundary gate proof.

The existing timeline's pure rotor decoder, lifecycle overlay and CAP1→Guest read/ACK→TIMG classifier were reused. A separate partial-provenance archive reader streams the215k-event -30 traces without modifying the strict200k/P1 guard; it always reports INCOMPLETE_PROVENANCE and never qualification. No scenario, firmware binary, CFG or missing event was generated or substituted. No experiments were rerun.

Validation:27 focused tests PASS;62 host tests/repository audit PASS;8/8 raw replays internally consistent with0 source errors. Missing/stale information, wrong command/count, sequence gaps, invalid/injected observer metadata, identity conflicts and large-stream separation from strict budget are covered. Synthetic unit fixtures remain test-only.

Detailed source findings and commands are on the updated [Draft PR11 branch](https://github.com/cctsao1008/escape32-qemu/blob/diag/e62-reference-startup-evidence/docs/current/e62-wsl-upload-replay-v2.md); machine-readable current acceptance/provenance is in `e62-engineering-evidence-v2.json`. The v1 report remains the prior snapshot. Exact Issue3 ELF/API access, fresh-task verification, changed-code SC5 handover, startup/restart defects, model measurements and hardware qualification remain unresolved as previously recorded.
