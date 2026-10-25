# G13B7.1 System Architecture

## QEMU device and immutable Guest

`machine/am13e23019.c` owns the AM13E QEMU Machine. Includes model
specific subsystems: `am13e_motor_feedback.inc` (CMPSS/ECAP),
`am13e_autonomous_sitl.inc` (opt-in QEMU DShot/BEMF/test timers),
`am13e_pa26_waveform.inc` (physical PA26 edges),
`am13e_trip_safety.inc` and `am13e_pwm_history.inc`.
The pinned Rel17.3 Guest ELF and its source-owned watchdog, CRC,
commutation, safety and PWM behavior are unaltered.

## Host code after refactoring

| Responsibility | Canonical implementation |
|---|---|
| QEMU MMIO ABI, scenario staging, exact Stage latch, aggregate oracle | `tools/sitl_autonomous_transport.py` |
| Read-only Stage sample summaries and timing event evidence | `tools/sitl_autonomous_evidence.py` |
| Rel17.3 sampled Stage functional acceptance | `tools/sitl_stage_oracle.py` |
| Original source-qualified WFI, real Zero-DShot ARM, GDB resume | `tools/native_arming.py` |
| Continuous Autonomous Guest observation, final evaluation | `tools/autonomous_sitl_runner.py` |
| Full CLI / Native preflight | `tests/functional_dshot_sitl.py` |
| Historical strict motor/rotor probe | `tests/g13b2_native_drive_probe.py` |

Compatibility contracts: `tools/autonomous_sitl_host.py` re-exports
the prior Host functions and constants; `tests/g13b4_functional_dshot_sitl.py`
delegates to the canonical CLI; `tests/g13b2_native_drive_probe.py`
re-exports the four Native arming helpers.

Do not merge hardware subsystem includes just to lower file count.
Do not mix scripted BEMF with motor physics, translate aggregate PASS
into rotor qualification or convert the independent strict G13B3M
known FAIL to an accepted result.
