# SC5 candidate integration regression v1

This executes the six nominal scenarios and eight existing analog-stress combinations after the isolated SC5 acquisition change. It is **not** Issue #3's exact-5b90b200 suite and does not contribute substituted evidence to that gate. Original055 is checked and left untouched. The test input is committed experimental source `bb02e4c`, no-reference-journal ELF `1452b4ec1575615662d2f9e9e793cbd15fb3e6a381d32bce2fc79fdfff54e1ab`, with existing 24V KV147 physics and virtual SC5 transfer profile. P1 predicates and thresholds are unchanged. This branch depends only on the separate passive-source parser fix; no experimental plant code is merged.

```sh
python3 tools/e62_sc5_candidate_regression.py \
  --candidate .build/mission-fw-sc5-fixed-no-journal/AM13E-rev17.3.elf \
  --original baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --cfg artifacts/mission-sc5/sc5-g13b3-cfg-flash.bin \
  --output artifacts/mission-sc5-regression --workers 4
PYTHONPATH=.:tests python3 -m unittest tests.test_e62_sc5_candidate_regression -v
```

The runner refuses an existing output directory or substitute ELF, records every exact probe/analyzer command, saves each strict P1 verdict, and preserves failed motor/identity outcomes. An expected experiment is not relabeled Original. The suite returns failure unless investigated as explicitly experimental evidence; it never grants P1/hardware approval. Two focused tests pass for exact plan cardinality/identity separation and rejection of substituted binaries. Full run results are versioned after completion.

## Completed matrix

All14 native probes completed their source DShot input with exit0. All strict P1 verdicts remain FAIL:11 include non-SHA motor/feedback failures, two retain the Original identity rejection only, and one is incomplete at the existing200,000-event parser budget. No threshold/budget was raised.

| Scenario | Stress | Significant reversals | Strict failures beyond Original identity |
|---|---|---:|---|
| smoke | nominal | 0 | none; still not Original P1 |
| gentle | nominal | 5 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| direct20 | nominal | 262 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| steps | nominal | 257 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| ramp20_100ms | nominal | 186 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| ramp20_500ms | nominal | 144 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| direct20 | 0:16 | 8 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| gentle | 0:16 | unavailable | INVALID_OR_MISSING_INPUT |
| direct20 | 16:0 | 60 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL, INSUFFICIENT_ORIGINAL_GUEST_CLOSED_LOOP_AFTER_ARM |
| steps | 16:0 | 126 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| direct20 | -16:0 | 58 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL, INSUFFICIENT_ORIGINAL_GUEST_CLOSED_LOOP_AFTER_ARM |
| ramp20_100ms | -16:0 | 58 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL, INSUFFICIENT_ORIGINAL_GUEST_CLOSED_LOOP_AFTER_ARM, NO_ORIGINAL_BEMF_COMPARATOR_FILTER_TRANSITIONS |
| direct20 | 16:20 | 336 | STARTUP_SIGNIFICANT_DIRECTION_REVERSAL |
| ramp20_500ms | 16:20 | 0 | none; still not Original P1 |

The gentle0:16 raw source log contains226,048 events and5000 DShot frames. The unchanged analyzer rejects its event budget before qualifying input; preserve that incomplete verdict rather than assuming mechanical health. Raw logs, strict reports and exact command arrays are retained for all14 cases.

`stress-provenance.json` independently verifies actual source analog perturbation diagnostics: offset-only cases emit three bounded samples with signed+16/-16; switching cases emit36 bounded active samples with signed16/20-code spikes; nominal cases emit none. These are source analog stress observations, not production calibration constants or a complete analog sample history.

The existing PR11 read-only analyzers were also replayed on the nominal and all four direct20 stress runs, with hash-verified experimental manifests and effective model readback. Their rotor/sample-age/clock/gate/CAP1 evidence is retained in `*.timeline.json` / `*.lifecycle.json`; private lifecycle states and missing/stale switches remain incomplete. Five direct20 replays completed without fabrication, independently of motor qualification.

No case is counted toward Issue3 exact5b90 qualification. The same-code SC5 liveness fix is supported as an acquisition correction, not a solution for startup/restart or offset robustness.
