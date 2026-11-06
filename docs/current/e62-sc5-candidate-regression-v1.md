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
