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

## Extended independent campaigns

- `e62-t02-functional.yml`: 110-second T02 11-stage 110,000-frame
  original-Guest regression. Zero-throttle and Stage transitions are
  separate strict sampled oracles; evidence uploaded on failure.
- `e62-safety-negative.yml`: QEMU external OC/nFAULT Trip hardware
  path, then four original-Guest fault ISR checks. A failing case is
  never counted as a PASS or bypassed.
- `e62-rotor-strict.yml`: source-built current QEMU + exact original
  Rel17.3 Guest, independent 12-sector/90ms strict gate and extended
  rotor direction. Does **not** rewrite historic pinned binary pairing.
- `e62-physics-host.yml`: current continuity / energy and reciprocity
  host-model checks, **not** Guest-coupled BEMF/RPM qualification.
- `e62-t01-repeatability.yml`: three same-host complete 11s T01
  repetitions; only repeatability, not G13B6 vs G13B7 speedup.

[Ten-item qualification status and strict evidence boundaries](validation-campaign.md).
