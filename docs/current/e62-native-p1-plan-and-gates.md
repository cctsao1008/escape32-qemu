# E62 Native No-WFI P1 — Startup, Analog Frontend, Fault Safety and Performance

**Scope:** source-built QEMU 6.2 AM13E23019, unchanged original
ESCape32 Rel17.3 ELF SHA256
`05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
P0 Strict qualified this 24V uncalibrated ECX87-KV147 model using
source-owned 1us current-continuous physics, rotor/BEMF → original
CMPSS/CAP1/TIMG12/Guest PWM feedback, without WFI/GDB or Host Guest
SRAM/MMIO control. P1 must NOT invalidate that P0 gate.

## Five work packages, strict qualification boundary

| Item | Implementation | Evidence and required next step |
| --- | --- | --- |
| P1-5 Startup / throttle | `tools/native_p1_qualification.py` + three real 1kHz JSON PA26 scenarios | Exact DShot command (frame index/CRC stimulus intent/virtual cadence) vs rotor unwrapped-angle RPM, time to first observed >=50RPM, time to 90% of **scenario's own observed** peak, coast RPM. NOT customer 8800RPM or calibrated acceleration. |
| P1-6 BEMF / OC frontend | QEMU source `BEMF_FRONTEND` and `OC_FRONTEND` events at native 1ms rotor clock | Current three phase code range, selected CMPSS0 mux, comparator threshold and filtered output; OC three-phase valid/ready/trip masks; no fake external BEMF injection or automatic comparator healthy bypass. Gain/offset model is STILL UNCALIBRATED. |
| P1-7 Negative fault, no-WFI | `scenarios/e62-native-p1-nfault.json` + `tools/native_p1_nfault_audit.py`, opt-in external PA22 physical signal | Assert at frame 2100, release at 2300 of independently clocked 3000-frame scenario. Require genuine native OST2, hardware IRQ, no continued PWM commutation, no auto re-arm. **Automatic recovery after fault is not qualified** and not expected from nonreturning Guest shutdown. |
| P1-7 Other independent fault negatives | `tools/ci/native_p1_fault_matrix.py`, existing `g13b2_native_fault.py`, bad PA26 CRC qualification | Four independent original-Guest trip ISR/shutdown tests and separate physical bad-CRC acceptance tests. These older cases **use controlled WFI/GDB**; do not represent a no-WFI running motor or signal-loss watchdog. |
| P1-8 Performance | `qemu_run_wall_elapsed_s`, virtual elapsed ns, native physics ticks, output-log size | Report measurable QEMU virtual seconds/host wall second and integration ticks/second. Not a fixed CPU benchmark (includes original Guest boot and QTest monitoring); no performance waiver for missing readings. |
| P1-9 CI and trace artifacts | `.github/workflows/e62-native-p1.yml` and `.github/workflows/e62-native-p1-fault.yml` | Each CI preserves QEMU stderr source event log, JSON and verdicts even on failure. Historical WFI Gates and previous P0 strict remain independently tracked. |

## Throttle JSON example

```json
{
  "schema": "e62.native.dshot.v1",
  "name": "P0 native 3s neutral slow ramp hold coast",
  "target_elf_sha256": "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0",
  "protocol": "DSHOT600",
  "frame_period_ns": 1000000,
  "guest_ready_gating": false,
  "stages": [
    { "kind": "hold", "duration_ms": 1500, "permille": 0 },
    { "kind": "ramp", "duration_ms": 1000, "from_permille": 0, "to_permille": 200, "update_ms": 5 },
    { "kind": "hold", "duration_ms": 300, "permille": 200 },
    { "kind": "hold", "duration_ms": 200, "permille": 0 }
  ]
}
```

The External Flight Controller always transmits PA26 DShot600 **every
1 virtual millisecond**, even while the original Guest boots and
handles faults. The positive range 48..2047 is a DShot command, never
physical measured duty or RPM. The Guest owns CRC, throttle acceptance,
arming, motor control and shutdown.

The independent external fault input uses a second versioned JSON
file (it does NOT modify the throttle schedule):

```json
{
  "schema": "e62.native.external-fault.v1",
  "source": "pa22_nfault",
  "assert_frame": 2100,
  "release_frame": 2300,
  "expectation": "OST2_LATCHED_AND_NO_AUTO_REARM"
}
```

The QEMU FC timer owns both fault edges, before the frame at the exact
virtual timestamp. No Host-timed polling or Guest TZ/IRQ direct write.
The fault case must NOT be evaluated by the positive no-fault rotor
strict gate; its pass criterion is the negative safe-off verdict.

## Running P1 after QEMU is built

```bash
python3 tests/e62_autonomous_native_motor_probe.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-native-autonomous-cfg-flash.bin \
  --scenario scenarios/e62-native-p0-gentle.json \
  --artifact artifacts/p1-gentle.json

python3 tools/native_p1_qualification.py \
  --scenario scenarios/e62-native-p0-gentle.json \
  --evidence artifacts/p1-gentle.json \
  --events artifacts/p1-gentle.p0.events.log \
  --output artifacts/p1-gentle.verdict.json
```

For nFAULT negative, add
`--fault-scenario scenarios/e62-native-p1-nfault.json`
to the native Probe and then run
`tools/native_p1_nfault_audit.py` with the source event,
throttle scenario, fault scenario and evidence arguments.
A `PASS_NATIVE_AUTONOMOUS_WIRING_SMOKE` is intentionally
**NOT emitted** for injected-fault runs.

## Out of scope / NO CLAIM

Neither P1 source-trace observation nor a successful fault shutdown
qualifies a 12S/propeller ESC, actual ECX87 performance at 24V,
Si/GaN switching losses, real current-sense amplifier offset/gain,
real comparator timing, thermals, safe re-arm following power cycling,
or signal-loss timeout. They require separately versioned acceptance
tests and actual bench correlation. The SIM_ONLY gain/bias and
physical-model placeholders must not be hidden by changing limits
until the reports show acceptable RPM.
