# Test Matrix — G13B7.1

| Scope | How to run | Correct interpretation |
|---|---|---|
| Autonomous Host/ABI/C behavior | `bash tools/ci/check_autonomous_host.sh` | All PASS; no native Guest claim |
| Custom pinned QEMU source | `./build.sh` | PASS_G0_BUILD |
| Bounded T01 smoke | `python3 tests/functional_dshot_sitl.py --autonomous --id T01 --max-frames 50 …` | Expected OPEN, never full PASS |
| Full T01 | `python3 tests/functional_dshot_sitl.py --autonomous --id T01 …` | 11,000 physical input frames; 11s; aggregate + both sampled Stages + neutral teardown |
| T02 | Same script with `--id T02` | 110s; OPEN until independently validated |
| Native peripheral bring-up | `./test.sh <original-ELF>` | Historical gate-wise acceptance |
| G13B3L strict six powered sectors | Pinned Native Regression workflow | Previously PASS |
| G13B3M strict 12 sectors / 90ms rotor | Same workflow, separate independent job | **Known FAIL**, retain it |
| Actual motor/ESC safety | Physical lab test | NOT QUALIFIED by SITL |

CI deliberately stays independent:
- `g13b7-correctness.yml` — current original Guest T01;
- `g13b3-host-unit.yml` — historical Host tests plus shared Host Contract;
- `e62-pinned-regression.yml` — paired immutable binaries and independent strict gates;
- `esc-sim-regression.yml` — full rebuilt firmware and native QEMU suite;
- `publish-e62-pinned-binaries.yml` — controlled baseline publication.

Speed comparisons require identical host, code, scenario and repeated
measurements; CI Ubuntu 24.04 wall time and local WSL Ubuntu 22.04
wall time are not directly comparable. Host performance counters are not
Guest CPU profile, nor are stimulus counts equivalent to ISR causality.
