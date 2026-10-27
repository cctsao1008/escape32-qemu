# E62 Native ESC–Motor P0 — Versioned DShot test scenarios

These files are executable **external Flight Controller** waveforms for
`tests/e62_autonomous_native_motor_probe.py`. They are not the legacy
`scenarios/e62-dshot-v1.json` Functional-SITL proposal. Format:
`e62.native.dshot.v1` and `e62-native-dshot-v1.schema.json`.

| File | Virtual timeline | Use |
| --- | --- | --- |
| `e62-native-p0-smoke.json` | 1500ms 0 → 1000ms 0–20% → 300ms 20% → 200ms 0 | Default P0 causal/rotor trace |
| `e62-native-p0-gentle.json` | 1500ms 0 → 2000ms 0–10% → 1000ms 10% → 500ms 0 | Slow ramp / starting behavior |
| `e62-native-p0-steps.json` | 1500ms 0 → 500ms 10% → 500ms 20% → 500ms 30% → 300ms 0 | Command step transients |

Every `duration_ms` sends that many **physical simulated PA26 DShot600
frames**, at exactly 1kHz in QEMU virtual time. `permille=0` sends
DSHOT value 0 (neutral). Positive integer permille is a *command* in
0.1% increments (100 permille = 10%, 1000 = 100%), converted
by existing QEMU firmware-independent test fixture to DShot 48..2047
using ties-to-even rounding. It is NOT shaft RPM, PWM duty or
measured torque.

Each `ramp` has exact integer-permille updates at `update_ms`
boundaries, but DShot is sent **every 1 ms** even if the commanded
value is unchanged. Between stages, the JSON is authoritative.
`guest_ready_gating=false` is mandatory: the external FC keeps
transmitting throughout original firmware boot/ARM/recovery; no QTest
readiness handshake may modify transmit scheduling.

Example use (after `./build.sh` and generation of original-ELF-only
SIM_ONLY preboot config):
```bash
python3 tests/e62_autonomous_native_motor_probe.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-native-autonomous-cfg-flash.bin \
  --scenario scenarios/e62-native-p0-steps.json \
  --artifact artifacts/e62-native-p0-steps.json
```

Each run preserves the chosen JSON SHA256 under
`native_dshot_scenario.sha256` plus source-owned
`*.p0.events.log` (CMPSS, CAP1, TIMG12, PWM power pair, rotor
unwrapped electrical angle/current, 120ms six-switch record and
current/energy invariants). Audit:
```bash
python3 tools/native_p0_reference_replay.py \
  --events artifacts/e62-native-p0-steps.p0.events.log \
  --output artifacts/e62-native-p0-steps.physics.json
python3 tools/native_p0_strict.py \
  --events artifacts/e62-native-p0-steps.p0.events.log \
  --evidence artifacts/e62-native-p0-steps.json \
  --physics artifacts/e62-native-p0-steps.physics.json \
  --output artifacts/e62-native-p0-steps.strict.json
```

The Python schema compiler rejects all unknown keys, invalid
ELF SHA, unsupported DShot rates, non-exact ramp fractions, non-neutral
start/end, and unsupported guest-ready gating. This does not imply
propeller calibration or 12S hardware qualification. A Wiring Smoke
PASS is **not** a strict rotor PASS; strict reports retain failures.
