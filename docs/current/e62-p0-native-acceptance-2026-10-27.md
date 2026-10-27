# E62 Native No-WFI P0 Acceptance Evidence — 2026-10-27

## Verified scope / evidence provenance

Repository: `cctsao1008/escape32-qemu`, **original ESCape32
Rel17.3** ELF SHA256
`05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
QEMU v6.2 source-built for AM13E23019; original CPU is never
halted by WFI/GDB and no host Guest SRAM, PWM, CAP1 or IRQ writes.
SIM_ONLY uncalibrated 24V ECX87-KV147 motor, 21 pole pairs,
no propeller load, modeled star currents and ideal diode freewheel.

**First full native P0 Strict PASS**:
[GitHub Actions run #40501541111](https://github.com/cctsao1008/escape32-qemu/actions/runs/40501541111),
run against main commit `60f0d4258920574326b660b001857576df785b24`.

This run preceded the later stronger physical CAP1/TIMG12 Guest
W1C-acknowledge proof and switch-instant current-continuity event
assertions. Do NOT promote the run above to a PASS of later
unexecuted exact-source strict checks. The new strict workflow remains
authoritative for the corresponding current main SHA.

## Source-backed first P0 CI measurements

| Measure | Evidence |
| --- | ---: |
| Independent 1kHz PA26 physical DShot600 frames | 3000 / 3000 |
| Original Guest CRC-accepted frames | 2871 |
| Original Guest CAP1 events | 830 |
| Original TIMG12 zero IRQ source events | 830 |
| Native Physics 1us timer ticks | 2,982,235 |
| Native switching notifications | 1,706,985 |
| Native analog BEMF code updates | 104,436 |
| Native model fault | 0 |
| Model OST3 latch activations | 0 |
| Rotor samples | 2982 |
| Peak absolute simulated rotor RPM | 479.295 |
| Significant rotor speed signs (>50 RPM) | + only |
| Source ordered CMPSS–CAP1–TIMG12–PWM pair chains | 829 |
| Source sector span | 1276.465 ms |
| Qualified distinct power pairs | 6 |
| Full physical six-pad switch records in first 120ms | 144 |
| Total event trace records | 12826 |
| Native cumulative backward-Euler physics steps | 4,675,238 |
| Native ideal-diode conduction intervals | 567,543 |
| Source energy serialization residual | 2 nJ maximum |
| Rotor angle/speed inconsistency count | 0 |
| Native motor end RPM (after external final DShot zero) | 5 |

**Frozen actual-six-pad 90ms independent Python CurrentContinuousBLDC**:

- Recorded actual QEMU switch events: 107
- Rotor comparison samples: 90
- Largest native-vs-host RPM deviation: `6.4931e-12 rpm`
- Largest native-vs-host electrical-angle deviation: `0.0004012244 rad`
- Largest native-vs-host phase-current deviation: `0.0004998763 A`
- 1us→0.5us vs 0.5us→0.25us terminal convergence:
  `0.0003220954` → `0.0001574240`.
- Frozen source replay verdict: `PASS_FROZEN_SWITCH_PHYSICS`.
- Original source event gate verdict at that commit:
  `PASS_NATIVE_P0_STRICT`, no waivers.

The first version of the event gate proved hardware callback order,
plus independent Guest CRC/service counts; it did **not** yet explicitly
log original CAP1/TIMG12 W1C acknowledge writes. Newer commits add
that evidence and check switch-instant inductor current continuity
at the actual model boundary. Therefore a later red CI must remain
red and investigated; it is not covered by the historical PASS.

## Versioned throttle scenarios

- `scenarios/e62-native-p0-smoke.json`: 1.5s zero, 1s 0→20%,
  300ms hold 20%, 200ms zero, every millisecond one DShot600 frame.
- `scenarios/e62-native-p0-gentle.json`: longer 0→10% ramp.
- `scenarios/e62-native-p0-steps.json`: 0→10→20→30→0 steps.
- `scenarios/e62-native-dshot-v1.schema.json`: file structure;
  `tools/native_dshot_scenario.py`: strict semantic validator.
- `scenarios/README-native-p0.md`: usage with JSON file arguments.

The original independent FC source always transmits in QEMU virtual
time, even before Guest startup/arming, while Guest owns reception,
CRC, safety protection and PWM commutation.

## Remaining qualification boundary

No **real** motor/propeller load validation, 12S bus power-stage model,
current-sense amplifier calibration, gate-driver delay, GaN loss,
thermal/power transient measurements, or silicon validation is claimed.

No pass has been inferred from historical G13B3M/G20 WFI
sampled-hold models. Legacy pinned binary/source-fingerprint CI jobs
may still fail for reasons independent of this new native P0 path.

**A particular main commit is P0 certified only if its own current
`E62 P0 No-WFI Strict Rotor, Causality, Physics` workflow passes
and retains source-owned trace + independent physics artifacts.**
