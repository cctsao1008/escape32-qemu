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


## First Verified Native P1 No-WFI Fault Gate PASS

GitHub Actions
[#40514844955](https://github.com/cctsao1008/escape32-qemu/actions/runs/40514844955)
completed successfully against the exact source at
`f75c290250ce11ecc401f29585123314160855f2`.
The original Guest ELF and QEMU physics are unchanged.

**Source-owned simulation evidence:**

- Continuous external PA26 DShot frames: **3000/3000**.
- Actual Guest valid frame feeds before non-returning fault shutdown:
  **1711**. After Guest disables IRQ, the external FC still sends.
  Its completed frame count is **not** original Guest CRC acceptance.
- The external PA22 nFAULT was asserted at QEMU virtual frame **2100**
  and released at frame **2300**. No Host timed poll or Guest
  synthetic PWM/TZ/IRQ write was used.
- Native MCPWM4 OST2 hardware bit `0x00020000` was asserted and
  **latched after physical release**.
- CPU final IPSR was **44** (original MCPWM4 IRQ), with
  `PRIMASK=1`, PC `0xA284` (original fault reset path).
- Rotor/PWM activity prior to the injected fault was genuine:
  203 original Guest CAP1/TIMG12 events. No later PWM pair
  commutation or final gate output was present.
- Native Motor model fault was 0; final six-bit gate mask=0.
- Separate source-owned verdict `PASS_P1_NATIVE_IN_FLIGHT_NFAULT_SAFE_OFF`,
  `qualified=true`, no waivers.

**Qualified:** Under the uncalibrated SIM_ONLY model, a real
external PA22 level has a modeled physical safety route into OST2,
with no automatic Guest rearm after its release; QEMU preserves the
exact event/frame evidence.

**NOT Qualified:** A recoverable in-flight shutdown/restart sequence,
a separate disarm/rearm command protocol, DShot signal-loss watchdog
reset, live Si/GaN hardware, 12S/propeller power, OC threshold accuracy,
or a real ECX87 motor. Do not count this PASS as recovery.

## Script-first policy, 2026-10-27

**The Python interactive console is frozen and is NOT a qualification
input.** Use a *fresh original Guest QEMU process per deterministic
versioned DShot source profile* and inspect real PA26/DMA/Guest ISR/
native switching, rotor dynamics, BEMF and current-sense source events.

After `./build.sh` and generation of the pinned SIM_ONLY preboot CFG:

```sh
python3 tools/e62_native_scripted_test.py --case smoke
python3 tools/e62_native_scripted_test.py --case gentle
python3 tools/e62_native_scripted_test.py --case steps
```

Omitting `--case` runs all four cases independently. The
`direct20` (1500ms neutral → 1500ms immediate 20% → 300ms neutral)
case distinguishes a direct acceleration step from the `steps`
scenario's initial 500ms stall at 10% before its first 20% command.
Both use the same Original Guest pin/physics, without scripted Guest
state mutation. Every run
saves `artifacts/e62-p1-scripted/e62-p1-script-<case>.json`,
`*.p0.events.log`, `*.p1.json`, probe/analyzer logs and
`e62-p1-scripted-matrix.json`. The process exits nonzero unless
**every specified case** has both a successful original-Guest
No-WFI Wiring Smoke and an independent P1 source strict verdict.

The fixed P1 DShot source-time oracle permits the *first* QEMU
physical timer callback to dispatch late within the existing 1ms
period (with at least 30us of next-frame idle). Subsequent frames
remain bound to absolute 1ms QEMU virtual deadlines with
no more than **100ns** of QEMU instruction-dispatch delay, an
explicit byte/word/time budget far below a 1.667us DShot600 bit.
Frame count, command, stage, index, Guest source ISR, BEMF, OC and
motor reversal checks remain fail-closed.

Historical CI [#40519051148](https://github.com/cctsao1008/escape32-qemu/actions/runs/40519051148)
contained QEMU physical source trace with 11 late callbacks of
**2ns** across 3000 Smoke frames, while Gentle and Steps
were precisely on deadline from Frame 1 onward. The old
audit incorrectly treated the first callback dispatch time as the
fixed source-timer epoch; that diagnostic error has been corrected.

**Steps remains truly OPEN / FAIL:** old native rotor trace had
no motion above 50 RPM during the initial 500ms at 10% command.
After stepping to 20%, it oscillated between positive and negative
RPM. The previous entire positive-command window had **223
significant direction reversals**. This is a motor-control/plant
dynamics problem, not a DShot clock issue; the Script-First
Matrix must remain red until the fixed source Guest control
proves stable. Do not tune down the 50RPM direction criterion
or substitute a Host WFI test to get green.

The script intentionally makes NO claims about loaded real ECX87,
12S, Si/GaN, hardware Trip calibration or recovered fault restart.

## Direct20 vs ramp startup physics root-cause isolation

Run with the **unchanged** original Rel17.3 Guest ELF and the Native
source event logs, without CLI, synthetic BEMF or a motor model patch:

```sh
python3 tools/native_p1_startup_transient.py \\
  --case smoke=artifacts/e62-p1-scripted/e62-p1-script-smoke.p0.events.log \\
  --case gentle=artifacts/e62-p1-scripted/e62-p1-script-gentle.p0.events.log \\
  --case direct20=artifacts/e62-p1-scripted/e62-p1-script-direct20.p0.events.log \\
  --case steps=artifacts/e62-p1-scripted/e62-p1-script-steps.p0.events.log \\
  --output artifacts/e62-p1-scripted/e62-p1-startup-transients.json
```

This script reads the ORIGINAL first 50ms after each case's first
positive DShot Frame and compares source-native current and torque
against CAP1, TIMG12 and first/second actual Guest PWM commutation.
It has `qualified=false` **by design**: it is a source-owned fault
isolation tool, not a way to override the failing P1 rotor gate.

The Oct 27 four-case CI artifact showed:

| Case | Max abs phase I (A), first 50ms | Lowest torque (N·m) | First -50RPM sample vs positive DShot | First original TIMG12 |
| --- | ---: | ---: | ---: | ---: |
| Smoke | 0.773 | 0.000 | no reversal | 19.996ms |
| Gentle | 0.483 | 0.000 | no reversal | 21.023ms |
| Direct20 | 45.250 | -3.509 | 7.209ms | 13.743ms |
| Steps (initial 10% stage) | 0 | 0 | no motion | 513.790ms (after 20% step) |

`direct20` rotor first reverses BEFORE the original Guest can
commutate into its second PWM sector; so a high-current startup
response in the first power pair is already unstable. It is premature
to attribute that first reversal to missing CAP1/TIMG12 IRQ delivery.
However, the model's current gain/zero-load mechanical dynamics and
real ESC startup duty calibration are **SIM_ONLY, not verified against
physical ECX87 hardware**. This is a root-cause *boundary*, not proof
of an original-firmware bug. Next experiments should isolate
startup duty slew and motor/propeller inertia with labeled A/B
parameters, preserving the originally pinned Guest and strict gates.
