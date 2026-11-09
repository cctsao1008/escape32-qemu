# Exact Issue3 qualification — 2026-11-07 (Asia/Taipei), v2

Status: **FAILED:14/14 executed;7 experimental non-SHA passes,7 failures**. Original P1 and hardware qualification remain false. This supersedes the earlier missing-artifact/executed0 state. No source firmware, QEMU physics/peripherals, scenario, acceptance threshold or Original identity guard was changed for the run.

## Independently verified inputs

The user-uploaded ZIP SHA is687d2a713f0d037de843e9717a8a82639b68aa0c233f587036486ac933c84139. Its filtered.elf is independently SHA256-verified as **5b90b200429333cef82b982b7a7f845f31fb885c7ea63fc7e783c75232fac8d1**. Its supplied336-byte CFG has SHA ab144c4b281ec53feb399b45c758b1de72b2c16f252e6ff64980f263b3a51702. No binary was rebuilt or substituted. Uploaded prior smoke/gentle logs remain separate evidence; they are not counted in the14 new cases.

Historical source contract:3ea4e672c0770db10c936531e7b3420b09473b18; user-provided historical artifact run40865298408/artifact12894011805. This execution is local Codex cloud, not a new GitHub Actions run. Source-built QEMU pin44f28df24767cf9dca1ddc9b23157737c4cbb645, executable6.2.0 SHA d5f4f5102469bb6dc4012682f4d7101d01b7c26fe7c3b29cd01a8c685ba7b943. Original ELF05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0 is reverified and unchanged. Runner commit6ab039a (full SHA in JSON) was executed in an isolated checkout to avoid branch-switch effects on running subprocesses.

```sh
source /workspace/setup-escape32/activate.sh
python3 tools/e62_exact_cmpss_suite.py \
  --candidate /workspace/escape32-qemu/artifacts/issue3-exact/uploaded-artifact-v1/filtered.elf \
  --original /workspace/escape32-qemu/baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --qemu /workspace/escape32-qemu/.build/qemu-src/build/qemu-system-arm \
  --cfg /workspace/escape32-qemu/artifacts/issue3-exact/uploaded-artifact-v1/e62-g13b3-filter-motor-cfg-flash.bin \
  --output /workspace/escape32-qemu/artifacts/issue3-exact/qualification-executed-v1 --workers 4
```

All seven group command arrays and per-case raw QEMU/source/probe/strict reports are retained. The aggregate exits1 and remains FAILED. Every strict report retains ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN; experimental non-SHA PASS never becomes Original qualification.

All14 new cases use the existing24V ECX87 KV147 unloaded SIM_ONLY plant and the default historical comparator path. They are separate from the47V KV210 c49 WSL cohort and the dynamic-SC5 candidate. No evidence is merged across those identities.

## Full results

| Stress | Case | Experimental result | Reversals | CAP1 ACK / TIMG12 ACK | Additional failures |
|---|---|---|---:|---|---|
| off | smoke | PASS_EXPERIMENTAL_ONLY | 0 | 1542 / 1541 | none |
| off | gentle | PASS_EXPERIMENTAL_ONLY | 0 | 2255 / 2255 | none |
| off | direct20 | PASS_EXPERIMENTAL_ONLY | 0 | 2742 / 2742 | none |
| off | steps | PASS_EXPERIMENTAL_ONLY | 0 | 2735 / 2735 | none |
| off | ramp20_100ms | PASS_EXPERIMENTAL_ONLY | 0 | 1905 / 1905 | none |
| off | ramp20_500ms | PASS_EXPERIMENTAL_ONLY | 0 | 2327 / 2327 | none |
| 0:16 | direct20 | FAIL_EXPERIMENT | 0 | 2742 / 2742 | DSHOT_VIRTUAL_CLOCK_OR_VALUE_MISMATCH |
| 0:16 | gentle | PASS_EXPERIMENTAL_ONLY | 0 | 2255 / 2255 | none |
| 16:0 | direct20 | FAIL_EXPERIMENT | 233 | 232 / 232 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| 16:0 | steps | FAIL_EXPERIMENT | 227 | 226 / 226 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| -16:0 | direct20 | FAIL_EXPERIMENT | 234 | 234 / 234 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| -16:0 | ramp20_100ms | FAIL_EXPERIMENT | 43 | 0 / 0 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL, INSUFFICIENT_ORIGINAL_GUEST_CLOSED_LOOP_AFTER_ARM, NO_ORIGINAL_BEMF_COMPARATOR_FILTER_TRANSITIONS |
| 16:20 | direct20 | FAIL_EXPERIMENT | 233 | 232 / 232 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| 16:20 | ramp20_500ms | FAIL_EXPERIMENT | 0 | 0 / 0 | INSUFFICIENT_ORIGINAL_GUEST_CLOSED_LOOP_AFTER_ARM, NO_ORIGINAL_BEMF_COMPARATOR_FILTER_TRANSITIONS |

Source analog stress provenance is present for all requested cases: nominal records emit no stress diagnostic; offset-only samples contain the requested signed offset; switching cases contain bounded active switching excursions. These remain relative model ADC-code perturbations, not measured board faults or production DAC calibration values. Per-case sample counts, source scenario hashes, speed signs, peak speed, PWM pair/CAP1/TIMG12 counts, strict failures and artifact hashes are retained in the versioned JSON. All failed raw evidence is preserved.

## Newly reproduced source-clock failure

0:16 direct20 has zero significant reversals but fails SOURCE_VIRTUAL_CLOCK at frame549: expected549551148ns, observed549551492ns,344ns late versus unchanged100ns budget. It is a failed case. The first frame has195636ns allowed startup lateness; subsequent deadlines are checked against the actual source epoch551148ns, not wall time or a presumed boot origin.

One identical-binary/CFG/scenario/QEMU repeat, stored separately as `clock-failure-repeat-v1`, passes the non-SHA gates with max observed dispatch error2ns. Its source epoch is26872ns rather than551148ns; initial source arming is not synchronized in the unchanged historical runner. Do not erase the first failure or claim identical initial VM states. The first run used a four-group concurrent suite and the repeat ran independently; host scheduling is not used as simulation time. The source timer schedules absolute deadlines (`am13e_autonomous_sitl.inc`), and the P0 logger samples the current virtual clock after PA26 wave scheduling. The present logs do not separate timer callback lateness from timestamp observation/dispatch effects; no proven scheduler-only cause or timing fix follows. Preserve the failure and investigate with source-owned scheduler evidence before closure.

## Offset failure chronology / coordination with Issues4 and5

Source DShot anchors, not a fixed1500ms guess, define each demand. All direct20 offset/control cases have a preceding sampled0RPM/-0.524rad rotor with zero sampled currents/torque; sample ages84–834us are retained rather than assumed exact boundary state. The first physical PWM pair payload is the same pair/pad pattern in the nominal and signed-offset cases.

+16 direct20 first sampled<-50RPM is+9.166192ms after actual demand; first CAP1 is+13.303392ms and first TIMG12+14.684580ms. The initial CMP_FILTER transition is falling at+10.647392ms; first CAP1 occurs later. Negative torque/reverse motion precedes accepted feedback. This is consistent with a biased low-BEMF crossing delaying commutation; it does not prove a firmware-only starting-sector defect.

-16 direct20 first sampled<-50RPM is+10.241860ms; first CAP1 is+4.335860ms and TIMG12+5.160024ms. This is post-feedback and requires crossing/phase/handoff analysis separately. -16 ramp100 never establishes the required comparator/CAP1/TIMG12 chain;16:20 ramp500 also has no CAP1/TIMG12 ACK despite zero significant reversals. Zero reversals are insufficient qualification.

The report retains first-positive and first20% source anchors separately, actual prior rotor payload/age, first PWM/CMP/CAP1/read/ACK/TIMG events and first reverse sample. Independently first T12_LOAD/START may precede the first capture, so their timestamps are not mislabeled as a capture's scheduling delay. Finite sampled rotor timing does not prove the exact physical threshold-crossing time. Bounded gate logs and analog publication/sample-epoch observability remain separate gaps.

## Acceptance

- DONE: recover exact ELF, verify its hash, preserve Original, execute14 cases, preserve every pass/failure/raw artifact and source stress provenance.
- FAILED: complete non-SHA robustness qualification;7 cases fail. No whole-suite PASS.
- IN_PROGRESS: DShot clock failure cause and biased startup/feedback integration corrections. Physical calibration values are not inferred from the model midpoint or stress codes.
- No merge, issue closure, production claim or hardware approval.
