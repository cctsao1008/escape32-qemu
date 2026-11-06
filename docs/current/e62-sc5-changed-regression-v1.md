# Changed-code SC5 integration regression — 2026-11-07 (Asia/Taipei)

New experiment, not Issue3 or the previous SC5 ELF. Source759a558b0714547b45fffc56b6a76ebd25efa575; no-reference-journal ELF d7a44dcda4f836ec6da15b19398af092cc79ff102b54778b0cd58bb245f9cba6. QEMU remains d5f4f510…/pin44f28; CFG ab144c4b…; unchanged scenario files. The full source/observer-free binary is pinned by the wrapper. Only the shared runner's identity parameters were factored; the old wrapper still pins1452b4ec. No strict analyzer predicates, limits or Original rejection change.

```sh
python3 tools/e62_sc5_changed_handover_regression.py \
  --candidate /workspace/escape32-qemu/.build/mission-fw-sc5-changed-no-journal/AM13E-rev17.3.elf \
  --original /workspace/escape32-qemu/baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --qemu /workspace/escape32-qemu/.build/qemu-src/build/qemu-system-arm \
  --cfg /workspace/escape32-qemu/artifacts/mission-sc5/sc5-g13b3-cfg-flash.bin \
  --output /workspace/escape32-qemu/artifacts/sc5-changed-handover/matrix-v1 --workers 4
```

All14 native probes complete their input with exit0. **All14 strict verdicts are FAIL**, including the retained Original identity rejection; no mechanical qualification is granted. SDK register tests prove the new sequencing/quarantine contract, but the constant-VBUS native scenario does not establish that a changed-code transition was exercised. Do not call register tests dynamic motor/hardware qualification.

| Scenario | Stress | Reversals | Strict failures |
|---|---|---:|---|
| smoke | nominal | 133 | DSHOT_VIRTUAL_CLOCK_OR_VALUE_MISMATCH, ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN, STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| gentle | nominal | 178 | ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN, STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| direct20 | nominal | 262 | ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN, STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| steps | nominal | 257 | ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN, STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| ramp20_100ms | nominal | 186 | DSHOT_VIRTUAL_CLOCK_OR_VALUE_MISMATCH, ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN, STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| ramp20_500ms | nominal | 229 | ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN, STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| direct20 | 0:16 | 8 | ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN, STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| gentle | 0:16 | None | INVALID_OR_MISSING_INPUT |
| direct20 | 16:0 | 60 | ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN, STARTUP_SIGNIFICANT_DIRECTION_REVERSAL, INSUFFICIENT_ORIGINAL_GUEST_CLOSED_LOOP_AFTER_ARM |
| steps | 16:0 | 91 | DSHOT_VIRTUAL_CLOCK_OR_VALUE_MISMATCH, ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN, STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| direct20 | -16:0 | 60 | ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN, STARTUP_SIGNIFICANT_DIRECTION_REVERSAL, INSUFFICIENT_ORIGINAL_GUEST_CLOSED_LOOP_AFTER_ARM |
| ramp20_100ms | -16:0 | 58 | ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN, STARTUP_SIGNIFICANT_DIRECTION_REVERSAL, INSUFFICIENT_ORIGINAL_GUEST_CLOSED_LOOP_AFTER_ARM, NO_ORIGINAL_BEMF_COMPARATOR_FILTER_TRANSITIONS |
| direct20 | 16:20 | 336 | ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN, STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| ramp20_500ms | 16:20 | 0 | ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN |

Nominal smoke, nominal ramp100 and16:0 steps include real source DShot deadline violations as well as reversal failures. Initial synchronization is enabled, so source-clock compliance is not guaranteed merely by pre-start synchronization. No timestamps are corrected or thresholds widened. Gentle0:16 exceeds the existing event-budget guard; its raw events remain available and its verdict incomplete. All source probe/analyzer command arrays, source logs and failures are retained.

The14-case result is a regression counterexample, not a green handover feature result. Sample freshness and native publication order are necessary but insufficient for controlled motor startup/restart. A dynamic-VBUS source integration test and a justified settling envelope remain software/physical gates respectively. No speculative production fix, model adjustment or DAC offset tuning is applied.
