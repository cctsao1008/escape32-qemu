# E62 Issue #5 — SIM_ONLY Initial Electrical Phase / Restart Causality (2026-10-30)

## Confirmed source evidence, not a hypothesized production fix

Historical real Guest/QEMU original-vs-cold-sector A/B
[CI #40894919388](https://github.com/cctsao1008/escape32-qemu/actions/runs/40894919388)
and [source torque replay #40905207362](https://github.com/cctsao1008/escape32-qemu/actions/runs/40905207362)
showed negative electromagnetic torque **before** first genuine new CAP1 in
the 300ms second demand. Both original oldstep and cold-sector strategies
reversed at 300ms; 1500ms and 3000ms cold-sector sometimes succeeded.
That invalidates unconditional `step=0` as a general solution.

At very low coast RPM the QEMU BEMF voltage model outputs only ≈1
ADC-like code of phase contrast. The QEMU `BEMF_FRONTEND` trace is a 1kHz
model journal, NOT a Guest ADC sampling limit nor a verified direction
measurement. No model theta/omega/torque enters the Guest.

## Explicit independent simulation profile

`configs/e62-sim-profile-matrix-v1.json` declares
`initial_electrical_degrees_grid=[-150,-90,-30,30,90,150]`.
The QEMU machine accepts an opt-in *whole-degree* setting:

```
-M am13e23019,esc-sim=on,esc-sim-native-motor=on,esc-sim-native-motor-profile=ecx87-kv147,esc-sim-native-initial-electrical-deg=90
```

The default remains **-30 degrees**. The motor reset uses that angle
as its initial *plant* electrical pose, not as information available to
Guest firmware. The append-only **read-only QTest model MMIO
`0x5FFEB0A0`** returns signed millidegrees for the configured initial
pose, verified independently by
`tests/e62_autonomous_native_motor_probe.py`. Validated input range is
`-180..180`; invalid or unsupported phase profiles reject.

This is a **boot-time initial phase experiment**. As the first demand
changes the simulated rotor trajectory, it does NOT hold second-demand
rotor phase and speed fixed independently. Use measured pre-demand
native `ROTOR` angle, RPM, and torque diagnostic outputs to separate
correlation from first-torque causality; never inject that model truth
back into the firmware.

## Current exact-source end-to-end gate

Workflow [E62 native restart phase sweep](../../.github/workflows/e62-native-restart-phase-sweep.yml)
runs Original Rel17.3 SHA
`05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`
on newly source-built QEMU with KV147 and 300ms coast, once at -30°
and independently at +90°. Both use exactly the same 5100-frame
source-owned 1kHz DShot fixture
`scenarios/e62-experimental-two-demand-coast-short300.json`.

The immutable original acceptance and independent source oracle are
computed **separately** in
`tools/e62_restart_phase_sweep_verdict.py`. Any significant negative
RPM or early negative model torque is retained as a genuine FAIL; the
workflow turns **RED** rather than manipulating Guest CAP1/Trip/PWM,
pretending that a source journal is a Guest sensor, or hiding evidence.
Artifacts (guest/source/QEMU JSON/events) are preserved even on FAIL.

- [CI #41085066994](https://github.com/cctsao1008/escape32-qemu/actions/runs/41085066994):
  first workflow run compiled QEMU but did not execute the motor due to
  a strict Flash Cfg filename provenance guard. This is an **INFRA FAIL**.
- [CI #41085796419](https://github.com/cctsao1008/escape32-qemu/actions/runs/41085796419):
  **REAL MOTOR FAILURE** under both genuine Original Rel17.3 / 5100-frame
  300ms-coast trajectories after fixing Flash Cfg provenance. No
  source/threshold waivers; independent original P1 and second-demand
  oracles both reject significant reversal.
  
| 300ms second-demand QEMU source metric | Initial −30° | Initial +90° |
|---|---:|---:|
| Rotor before demand (RPM) | +34.557 | +20.786 |
| Internal electrical angle before demand | 133.911° | 266.733° |
| First new CAP1 delay | 7.141ms | 7.305ms |
| First new model torque | **−0.73472 Nm** | 0 Nm |
| Rotor samples ≤−50 RPM in first 20ms | **10** | **5** |
| First powered demand sustained forward / zero reverse | FAIL | FAIL |
| Second powered demand sustained forward / zero reverse | FAIL | FAIL |
| Immutable Original P1 strict mechanical | FAIL | FAIL |

Crucially, *first-start* also fails the new independently sustained
positive-motion criteria for both initial poses: do not claim that
only the remembered oldstep across the coast caused the failure.
These are modeled torque/RPM, not Guest rotor sensors.

### Additional actual firmware ADC path limitation and simulation fix

Before the new opt-in model, native QEMU BEMF drove CMPSS but ADC0/1/2
sequencer results still came from fixed/external `channel_samples`.
The Firmware source at `ESCape32@b020467` actually maps three-phase
monitoring through ADC0 SOC1 CH12 (U), ADC1 SOC2 CH2 (V), and ADC2 SOC1
CH5 (W); these original Guest raw ADC samples had not been connected to
the same native motor rotor plant.

`esc-sim-native-adc-bemf=on` (default **off**) now selects native
motor BEMF codes ONLY for these three correctly programmed ADC SOCs
upon real source-triggered EOC/IRQ. All other ADC channels preserve
their existing fixture and signal flow. Invalid channel or plant-fault
state refuses to manufacture a valid phase conversion. QTest provides
individual ADC phase EOC publication counts at the append-only model
observer offsets `0xA8/0xAC/0xB0`. This is simulated raw phase voltage,
**not rotor angle**, direction, trusted rearm status, or calibrated board
sensing. Phase mapping is pinned to the versioned JSON profile, with
negative tests rejecting unsupported mapping/rearm.

[CI #41087374861](https://github.com/cctsao1008/escape32-qemu/actions/runs/41087374861)
**SUCCESS** on exact source-built QEMU and immutable Original Rel17.3
Guest, with **2,994 / 2,994 / 2,994 actual source-owned ADC0/1/2
SOC/EOC phase publications**, true EOC/IRQ in Guest-driven scan. The
no-angle/no-rearm profile/unit job also passed.

To distinguish changing model samples from constant 2048 dummy reads,
the follow-on `266770e9385c7c74be920ac37eb09bdd00014e98` additionally
counts (a) **non-midscale** BEMF EOC codes separately for each phase,
and (b) **actual Guest ADCRESULT MMIO reads**. Strict CI
[#41088019547](https://github.com/cctsao1008/escape32-qemu/actions/runs/41088019547)
requires all six additional counters >0; **pending final live QEMU
verification** at time of writing. These counters cannot qualify rotor
direction/phase confidence or the guest's automatic rearm.

- Existing dual-motor OC source-protection regression is preserved
  separately and must remain PASS after the append-only observer change.

## SIM_ONLY closure boundary

A working general sensorless restart **is not yet proven**:
- 300/1500/3000ms neutral/coast and near-stall source-owned stages;
- both applicable directions, actual reliable phase/rotation inference
  when sensorless BEMF is observable;
- a safe refusal/settle/reacquire policy for unobservable ~1LSB state
  that does not fabricate angle, trip, or motor authorization;
- strict Original P1 and source-built candidate separation, no
  significant reversal, with actual Guest feedback and motor trajectory;
- both KV147/KV210, plausible bounded analog noise/clock profiles.

A static initial sector cannot force positive electromagnetic torque
for all rotor electrical angles, because the torque of a fixed
two-phase current vector depends on rotor position and changes sign
over a complete revolution. A verified direction/phase estimator or
a physically enacted, bounded low-speed alignment method is needed
to meet a global no-significant-reversal test. The simulation is
qualified only to the explicit tested profile/stages; **no physical
hardware measurements block these SIM_ONLY software tests**.

**Issue #5 remains OPEN.**

## 2026-10-31 — Real Guest ADC epoch-and-phase-rank acquisition gate

The first [real Original-Guest ADC source CI #41088019547](https://github.com/cctsao1008/escape32-qemu/actions/runs/41088019547) completed **SUCCESS** with independently measured:
- Each ADC0/1/2: **2,988 true hardware-modeled SOC/EOC publications**, and **2,988 actual Guest ADCRESULT reads**.
- Dynamic (non-2048) BEMF-derived EOC codes: ADC0/U 1,053; ADC1/V 1,056; ADC2/W 1,269.
- No Guest register injection or self-rearm. The original unchanged protection profile matrix [#41088020827](https://github.com/cctsao1008/escape32-qemu/actions/runs/41088020827) also completed **SUCCESS 6/6** for KV147/KV210 OC-U/V/W.

These counts establish a *data path*, not positive motor direction.

Source [commit `8dc27daf`](https://github.com/cctsao1008/escape32-qemu/commit/8dc27daf83c5e4d308d57fdf4772380dfea40796)
adds **opt-in, source-only** `ADC_PHASE_EOC` and `ADC_PHASE_READ`
events from actual QEMU ADC sequencer completion and actual Guest
ADCRESULT accesses; each is timestamped, contains the source read
code and ADC/SOC/channel/epoch, and **does not expose motor model
theta/omega/torque**. Default mode, Original P1, motor physics and
production policy are unchanged.

[`tools/e62_guest_adc_phase_coast_audit.py`](https://github.com/cctsao1008/escape32-qemu/blob/main/tools/e62_guest_adc_phase_coast_audit.py)
requires exact independent DShot frames; three coherent fresh Guest
phase read epochs; EOC→Guest read equivalence; read timestamps and
SOC/channel provenance; plus no Guest motor commutation 200ms into
coast. It separately evaluates **the first and last 100ms of coast**,
using Guest-visible code contrast and six-phase-code ordering.
Ambiguous ties, skipped ranked-sector transitions, mixed order,
invalid samples, missing/duplicated EOCs, wrong channel and stale
Guest reads are negative controls. A candidate rank order is
*diagnostic only*: `motor_rearm_permitted=false`,
`passive_rotor_direction_qualified=false` and
`original_P1_reacquisition_qualified=false` ALWAYS.

All 11 host negative tests in
[`tests/test_e62_guest_adc_phase_coast_audit.py`](https://github.com/cctsao1008/escape32-qemu/blob/main/tests/test_e62_guest_adc_phase_coast_audit.py)
run in [new dual-motor real QEMU coast CI #41095093474](https://github.com/cctsao1008/escape32-qemu/actions/runs/41095093474).
The negative host CI is **PASS**; do not claim the actual motor source
coast qualification PASS until those jobs complete. The earlier
source-only failure [300ms initial-phase CI #41085796419](https://github.com/cctsao1008/escape32-qemu/actions/runs/41085796419)
continues to **FAIL** for genuine rotor reversal and must remain red.

This is **SIM_ONLY** work; no physical hardware checks are required.
The remaining feature gap is firmware-owned, source-observable
windmill direction/phase qualification and a safely bounded
low-observability startup/restart handoff, not the ADC wiring.
