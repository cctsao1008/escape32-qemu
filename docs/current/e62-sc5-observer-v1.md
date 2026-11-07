# Issue #4 native SC5 evidence observer v1

The optional `--reference-diagnostics` flag resolves uniquely named experimental
SRAM symbols from the exact ELF and performs read-only QTest reads after the
input scenario. It rejects Original Guest use and absent/ambiguous symbols.
There is no Guest write, breakpoint, fake capture, or injected reference code.
The companion firmware branch is `diag/e62-sc5-acquisition`, commit 783252d,
not an Original or Production Root Fixes binary.

The journal is bounded first64/last256 with sequence-last commits. Concurrent
updates, uncommitted rows and missing history remain incomplete. MCU SysTick
and ECAP counters retain their own epochs; they are not labeled QEMU absolute
virtual nanoseconds. Freshness/wrap and state invariants do not grant P1 or
hardware qualification. The source publication proof flag remains false because
absolute source-MMIO/counter-epoch correlation and physical phase/polarity are
not fully represented by this journal alone.

The explicit virtual calibration network uses acquired VBUS ADC codes and the
existing checked rational conversion. No production DACH midpoint or +/-16
calibration value is installed. The current test is a static virtual bus/network
fixture, not a measured PCB or varying-bus qualification.

Native baseline failure: reference sample 1487 was published/armed at age27;
at age33 with max_age32, sample1488 was already valid but the staged association
was still1487. The actual firmware entered fault reset, with no CAP1. The
original policy fails closed as designed but cannot sustain this acquisition
contract without refreshed publication association. Native input/wiring smoke
PASS is NOT CPU/control/closed-loop PASS: autonomous input continues while the
Guest has stopped in fault reset. The independent qualification remains failed.

An isolated experimental firmware branch tests equivalent-code refresh at ZERO.
Its successive failures are retained under ignored artifacts/mission-sc5, not
replaced by an optimistic result. Control-policy changes are not mixed into this
QEMU diagnostic commit. The existing 32-tick limit and original P1 are untouched.
Changed-code tracking and actual board calibration are not claimed.

```sh
python3 -m unittest tests.test_e62_reference_observer \
  tests.test_e62_issue5_bemf_diag tests.test_e62_native_qtest_pipe_and_trip_log -v
# Build the pinned experimental firmware with its explicit virtual profile,
# then pass its actual sha256 via --experimental-candidate-sha256:
python3 tests/e62_autonomous_native_motor_probe.py \
  --qemu .build/qemu-src/build/qemu-system-arm --elf EXPERIMENT.elf \
  --experimental-candidate-sha256 SHA256 --reference-diagnostics \
  --cfg-flash artifacts/mission-sc5/sc5-g13b3-cfg-flash.bin \
  --scenario scenarios/e62-native-p0-direct20.json \
  --sim-motor-profile ecx87-kv147 --sim-native-adc-bemf \
  --differential-sync-start --wall-timeout-s 300 --artifact evidence.json
```

Five observer tests and nine existing BEMF/QTest tests passed. Existing official
SDK register tests exercise missing/stale/invalid reference, wrong sync, wrong
active DAC, delayed publication and phase association; they remain a separate
host/register evidence class. Historical +/-16 raw cause-map and exact Issue #3
ELF are not available due to artifact/API access. No issue is closed.
