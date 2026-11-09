# Issue #3 exact CMPSS replay v1

The historical 14-case runner was restored unchanged from QEMU commit
7ae89441f4224fccd414a7c1c4fa72e488dcdcec. The new orchestration wrapper enumerates
the exact six nominal cases and eight stress cases, preserves all non-SHA P1
criteria, and refuses any candidate other than SHA256
5b90b200429333cef82b982b7a7f845f31fb885c7ea63fc7e783c75232fac8d1.
Original SHA rejection remains active. All motor source/CFG/QEMU artifacts and
failed case logs must be retained. Group launch is not case completion.

User-supplied exact artifact:
https://github.com/cctsao1008/escape32-qemu/actions/runs/40865298408/artifacts/12894011805

Download observations in this cloud: the GitHub web artifact URL returned HTTP
404; `gh api repos/cctsao1008/escape32-qemu/actions/artifacts/12894011805/zip`
returned `Forbidden` for api.github.com. This does NOT prove that the archive is
absent or its bytes incorrect. The running enforced network policy does not
include api.github.com; a draft addition has not changed runtime access.

The older source was recovered at ESCape32 commit
3ea4e672c0770db10c936531e7b3420b09473b18 and successfully built with GCC14, but
that binary differs from the exact pinned ELF. It was NOT substituted or run as
the Issue #3 qualification candidate. No 14-case results are fabricated.

```sh
python3 -m unittest tests.test_e62_exact_cmpss_suite -v
python3 tools/e62_exact_cmpss_suite.py \
  --candidate artifacts/issue3-exact/filtered.elf \
  --original baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --cfg artifacts/e62-acquisition/e62-g13b3-original-cfg-flash.bin \
  --output artifacts/issue3-exact/qualification --workers 2
```

Current outcome: two orchestration/identity tests PASS; native cases 0/14
executed, BLOCKED_EXTERNAL pending authenticated archive access or a supplied
exact archive. Existing four-case A/B is historical SIM_ONLY evidence, not a
14/14 pass. The suite refuses a source-equivalent rebuilt substitute.
