# Issue10 historical WSL trace replay — v2 (2026-11-07, Asia/Taipei)

The uploaded archive supplies the three requested **raw trace datasets** and five additional repeats. All eight JSON summaries, stdout records and raw/QEMU event streams are internally consistent. Full historical provenance is still incomplete: no standalone scenario JSON, CFG image/hash, guest ELF/source build manifest, QEMU executable hash/build manifest or exact launch command was included. No replacement binary, scenario or CFG was generated. No QEMU experiment was rerun.

Archive SHA256: `7fe331fc3ede1290cc63afc00db217baa37b041a0868e9918e77eefd7c2ad8ea`;24,646,661 bytes;33 members. The three required names are `sync-angle-030-repeat01`, `sync-angle-090-repeat01`, `sync-angle-090-repeat02`. Each has a raw `.p0.events.log`, full `.qemu.log`, `.stdout.log` and summary `.json`. Their availability supersedes the raw-log-unavailable statements in v1; the earlier independent cloud cohort remains a different experimental identity.

## Identity and validation

Every summary declares Production Root Fixes ELF `c49a7485af218966a2e3ec764de8d997d8ba478954dcad42b88c0c99e4f3c003`. This is not Original Rel17.3 `05563b69…`, nor the Issue3 filter ELF `5b90b200…`. The c49 binary is not present for independent verification. The embedded scenario declaration targets the historical Original template but does not change the actual reported guest identity.

Each reports KV210/47V/no-prop,200MHz MCPWM root, native ADC BEMF, historical_sine, initial pause before the first instruction, synchronized start, no host Guest-register writes/GDB/synthetic BEMF, and focus2995:3040ms. These are reported settings/readback, not independently verified build/CFG identities. Scenario SHA is declared `3e1e5ed4b352fecbba79977b84fae507f85b2649d846469abd0451b44fda5184`; exact bytes are absent.

The embedded stage table is independently checked against every source DShot frame:1500ms neutral,1500ms20%,20ms neutral,1500ms20%,300ms neutral;4820 frames. Legacy `dshot_profile` default fields (including200ms coast) do not describe this selected scenario. Absolute source anchors are100,1500000100,3000000100,3020000100,4520000100ns. Host wall timestamps never define chronology.

All source sequences are contiguous and virtual time is monotonic. Extracted event tuples match each full QEMU log, raw counts match the JSON, and the final stdout JSON matches its sidecar. The -30 traces contain215,443 and215,430 events. The existing strict200,000-event reader/P1 budget remains unchanged; the archive inventory streams full supplied files under a separate64MiB resource bound and never grants qualification.

## Actual sampled boundary states

The table uses the immediately preceding source ROTOR sample. Angle is wrapped electrical degrees; speed is signed mechanical RPM. Age is explicit; these are sampled model states, not exact boundary measurements or hardware readings.

| Dataset | Boundary (absolute ns) | RPM | Electrical angle ° | Sample age ns | Gate evidence |
|---|---:|---:|---:|---:|---|
| sync-angle-030-repeat01 | 1500000100 | 0.000 | 329.977012 | 157036 | INCOMPLETE |
| sync-angle-030-repeat01 | 3000000100 | 2329.052 | 92.305626 | 143160 | OBSERVED |
| sync-angle-030-repeat01 | 3020000100 | 2292.744 | 154.817331 | 142984 | INCOMPLETE |
| sync-angle-030-repeat01 | 4520000100 | 2332.598 | 15.942905 | 130336 | INCOMPLETE |
| sync-angle-090-repeat01 | 1500000100 | -6.066 | 287.438099 | 157036 | INCOMPLETE |
| sync-angle-090-repeat01 | 3000000100 | 879.803 | 3.223513 | 154988 | OBSERVED |
| sync-angle-090-repeat01 | 3020000100 | 933.714 | 213.320728 | 154984 | INCOMPLETE |
| sync-angle-090-repeat01 | 4520000100 | 2328.326 | 128.665135 | 141660 | INCOMPLETE |
| sync-angle-090-repeat02 | 1500000100 | -6.066 | 287.438099 | 156608 | INCOMPLETE |
| sync-angle-090-repeat02 | 3000000100 | -143.852 | 325.903670 | 155316 | OBSERVED |
| sync-angle-090-repeat02 | 3020000100 | -262.103 | 330.508567 | 155316 | INCOMPLETE |
| sync-angle-090-repeat02 | 4520000100 | 7.081 | 216.519430 | 154656 | INCOMPLETE |

The20ms neutral stage does not establish rest: second-demand speeds are+2292.744,+933.714 and-262.103RPM respectively. Both -90 repeats begin their first demand at sampled -6.066RPM /287.438099°, despite configured initial angle -90°. Rotor movement precedes demand. The actual source sample replaces any assumed stationary initial/restart angle.

MCPWM divider observations mark audio-clock candidate intervals11.383152–386.440024ms and637.006432–887.064888ms in these required traces. The existing lifecycle tool labels these inferred candidates; it does not directly observe private Boot Audio/arming ownership, nor prove audio exclusion. Source gate/switch logs are bounded and the final journal is a128-record ring with drops. Missing or stale boundary gate state remains INCOMPLETE, even when a nearby rotor sample is fresh.

## Divergence and feedback

| Pair | First source mismatch | Absolute vns A / B | Interpretation |
|---|---|---|---|
| sync-angle+000-repeat01 /02 | ROTOR seq7613 | 515842576 / 515842972 | Same reported settings; exact matched provenance unverified |
| sync-angle+090-repeat01 /02 | ROTOR seq19043 | 1333843100 / 1333843064 | Same reported settings; exact matched provenance unverified |
| sync-angle-030-repeat01 /02 | CMP_FILTER seq22965 | 1535659120 / 1535659344 | Same reported settings; exact matched provenance unverified |
| sync-angle-090-repeat01 /02 | ROTOR seq19266 | 1349843064 / 1349843492 | Same reported settings; exact matched provenance unverified |

For -90, the earliest difference is428ns at a ROTOR event1.349843064/1.349843492s, before first demand; payloads initially match. Later outcomes diverge strongly. This is observed chronology, not proof of QEMU nondeterminism or a firmware-only defect: CFG bytes/build identities are missing. The -30 pair first differs at CMP_FILTER35.659020/35.659244ms after first demand.

Both -90 first starts have sampled reverse speed below-50RPM at approximately+7.843ms after demand, after their first source CAP1 at approximately+3.614ms and first TIMG12 at+4.485ms. This specific early reversal is post-feedback. In -90 repeat02 the second demand begins already rotating backward: the first post-boundary reverse sample is+0.844684ms with zero sampled current/torque; it must not be described as a newly generated reversal caused by that demand. No absence of reverse samples in -30 is promoted to independent startup qualification.

The report preserves first physical PWM_PAIR, CMP_FILTER, CAP1, Guest CAP1 read/ACK, T12_LOAD/START and TIMG12/ACK source events per stage. It reuses the existing capture-window classifier for first25ms, marking the final window right-censored. Independent first-event times are not an asserted causal chain: initial T12 programming can precede the first CAP1. Missing sample identity/epoch and active DAC publication proof remain incomplete.

## Reproduction and tests

```sh
python3 tools/e62_uploaded_trace_inventory.py \
  --directory artifacts/issue10-wsl-upload-v1/startup-determinism \
  --output artifacts/issue10-wsl-upload-v1/replay
PYTHONPATH=.:tests python3 -m unittest \
  tests.test_e62_uploaded_trace_inventory tests.test_e62_acquisition_timeline \
  tests.test_e62_lifecycle_alignment tests.test_e62_issue5_cap1_timer_audit -v
bash tools/ci/check_autonomous_host.sh
```

Results:8/8 source replays internally consistent;0 source errors;27 focused tests PASS;62 host tests/repository audit PASS. CLI success means the inventory/replay completed, while its status remains INCOMPLETE_PROVENANCE. Tests cover source gaps/unknown records, command/count mismatch, injected/missing observer contract, Original/Production distinction, stale/missing gate state, partial-pair provenance, full archive comparison, and reading>200k archived records while the strict guard still rejects them. Synthetic unit fixtures never become engineering evidence.

## Updated acceptance

| Gate | Status |
|---|---|
| Required three raw event streams and matching runtime summaries | DONE |
| Real source DShot/boundary/feedback replay | DONE, with explicit sampling and lifecycle gaps |
| Full scenario/CFG/ELF/QEMU/launch provenance | BLOCKED_EXTERNAL: omitted archive members |
| Private lifecycle ownership, full gate waveform, SC5 identity/epoch publication | IN_PROGRESS / not exposed by these logs |
| Matched-provenance scheduling attribution | BLOCKED_EXTERNAL for matching identities; causal conclusion unsupported |
| Strict Original P1 or Issue5 startup/restart qualification | NOT SATISFIED; not granted by this replay |

To complete provenance, recover the exact referenced `artifacts/issue5/ztc-robustness/scenario-coast020.json` (required SHA above), CFG bytes and SHA, c49 ELF/source/SDK/toolchain manifest, QEMU executable SHA/source/build manifest and launch command/configuration. Do not replace them with cloud binaries or reconstructed scenario bytes. The actual uploaded raw evidence is now available; the remaining blocker is specific omitted provenance and unobserved signals. No firmware, physics, peripheral behavior or acceptance threshold changed. No merge or closure.

## Existing experimental launcher cross-check

Read-only review of repo commit `204fe85a512fff9ea0cfdfe430a29132c52197c4`, `tools/e62_issue5_startup_repeatability.py`, finds the same dataset names, c49 ELF and3e1e5ed4 scenario contracts. It pins expected CFG `77366cfe9f0632b795a72393f7f0e990a99e8af92429cbb82d42bbb3f7c8ed4b` at `artifacts/issue5/ztc-ab/B-ztc1-damp1.cfg.bin`, with byte21 DAMP=1 and byte40 THROT_ZTC=1. Its command builder agrees with the reported200MHz/native-ADC/historical_sine/focus2995:3040/synchronized-start setup. This is an existing **source contract**, not proof of the exact executed launcher or CFG bytes in the uploaded runs. Its driver normally prints QEMU SHA before per-case stdout; that top-level driver output was not included. Recover that output/build manifest as well as the pinned CFG. No control code from the branch was merged.
