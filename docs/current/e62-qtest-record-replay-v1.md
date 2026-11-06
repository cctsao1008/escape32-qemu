# QTest record/replay transport and fail-closed finalization — v1

This is isolated debug infrastructure. It changes neither QEMU peripherals/physics nor Guest firmware nor P1 acceptance. It is not a qualification waiver or a replacement for the missing historical WSL bundles.

## Verified defects

In pinned QEMU `44f28df24767cf9dca1ddc9b23157737c4cbb645`, `softmmu/qtest.c:qtest_server_init` constructs the debug socket with `qemu_chr_new`. That wrapper enables character replay. The initial diagnostic QTest read is queued as a replay character event while the CPU is intentionally paused before its first instruction, so pre-start polling times out (VM alive, zero-byte recording). The optional, guarded `tools/ci/prepare_qtest_noreplay.py` uses QEMU's existing `qemu_chr_new_noreplay` API for that debug transport only. It rejects a different source pin or a missing/duplicate anchor and is idempotent. It is never silently applied by setup or by normal qualification.

After that transport patch the 4820-frame record run completes, but the old probe's QMP teardown sends `quit` then immediately closes the socket. In the first run the VM never exits, is killed after 12 seconds, and the RR file is incomplete despite a wiring-smoke status. The corrected helper consumes QMP events until command acknowledgement or EOF and independently requires zero process exit. The probe now records `FAIL_RECORD_REPLAY_FINALIZATION` and raises after saving evidence if shutdown fails. It retains the prior status as a separate diagnostic field; an incomplete record must not be replayed as a valid experiment.

The corrected recording in `artifacts/mission-rr-qtest-fixed-v2/record.json` exits 0, finalizes 88,536,807 bytes, and passes wiring smoke. This does not prove the motor's rotor qualification or that replay matches. The first incomplete recording and timeout replay remain preserved in `artifacts/mission-rr-qtest-fixed/`; they are invalid infrastructure experiments, not motor verdicts.

## Reproduction

```sh
python3 tools/ci/prepare_qtest_noreplay.py --source /workspace/escape32-runtime-evidence/.build/qemu-src
ninja -C /workspace/escape32-runtime-evidence/.build/qemu-src/build qemu-system-arm
PYTHONPATH=.:tests python3 -m unittest tests.test_e62_qtest_noreplay tests.test_e62_rr_teardown -v
```

Five focused tests pass: unique source anchor/idempotence, rejection of missing/duplicate anchors, QMP event/ack consumption, EOF plus independent process verification, and rejection of QMP errors. Actual full QEMU experiments are separately versioned with complete command arrays, binary SHA256 and raw source event logs under `artifacts/mission-rr-qtest-fixed-v2/`. They use experimental source-53953c firmware and the existing 204fe85 experimental QEMU implementation, not c49a7485 Production Root Fixes or Original055. `-icount shift=2,sleep=off,align=off` was already enabled in the non-RR cohort; RR adds event recording, not that timing option.

QTest queries are debug-side observations. Excluding the query transport from character replay does not establish deterministic query arrival, nor may host wall times be used for event chronology. Compare absolute source `vns`/event identities before claiming determinism. No synthetic event may fill a missing replay interval.

## Finalized source replay result

`tools/e62_rr_source_compare.py` verifies sequential/monotonic source records, complete indexed DShot input, matching firmware/scenario/effective-profile identities, finalized zero-exit processes, and exact tuples including absolute virtual timestamps. It reports `PASS_EXACT_SOURCE_RR_REPLAY` for 74,596 events / 4820 frames. Both raw event files have SHA256 `c7c7063035f6ddfc76525b9ab8719f05abfc87dd6bcd5706ca486c625056c5e9`. The live replay probe **FAILS** (`QEMU exited during autonomous motor test`): QEMU exits at the recorded end before the host's final poll. That failure and missing final observation are retained in the comparison output, not converted to a live-probe PASS. This result demonstrates replay of this recorded event history, not identical independent boots or motor success. Ten focused tests cover transport/QMP plus incomplete or corrupt input, absolute timestamp mismatch, provenance mismatch and preserving host failure.

```sh
python3 tools/e62_rr_source_compare.py \
  --record artifacts/mission-rr-qtest-fixed-v2/record.p0.events.log \
  --replay artifacts/mission-rr-qtest-fixed-v2/replay.p0.events.log \
  --record-evidence artifacts/mission-rr-qtest-fixed-v2/record.json \
  --replay-evidence artifacts/mission-rr-qtest-fixed-v2/replay.json \
  --output artifacts/mission-rr-qtest-fixed-v2/source-comparison.json
```
