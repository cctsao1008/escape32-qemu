# E62 Issue #5 — First-Demand Torque Reversal Before First Commutation (Source Evidence)

2026-10-31 | **SIM_ONLY diagnostic; unchanged Original Rel17.3; no FW bug claim; no Original P1 waiver.** The trace below is from **historical 100MHz QEMU clock** on the 24V KV210 motor-only Original Guest baseline, not from the new 200MHz experiment.

## Exact provenance / reproducer

- [24V baseline run #41178267331](https://github.com/cctsao1008/escape32-qemu/actions/runs/41178267331), job `BASE-KV210-24V-NOPROP`, archive `e62-24v-BASE-KV210-24V-NOPROP-300-SIM-ONLY`.
- Source data file inside the archive: `BASE-KV210-24V-NOPROP-300.p0.events.log`, 69,580 first-party QEMU virtual-clock events.
- Original Guest SHA-256 `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
- First positive 20% DShot command starts at `vns=1500025708` (source-clock virtual nanoseconds). The table shows event time **relative** to that timestamp.
- Source `ROTOR.a` in milli-RPM, `ROTOR.f` in micro-Nm; `CMP_FILTER.a` selects U/V/W index 0/1/2; `CMP_FILTER.b` comparator filtered level; `PWM_PAIR.a` is the native physical modeled high/low pair encoding.

## Model behavior before any *next* six-step pair

| Time since 1st 20% DShot (ms) | Source event | Rotor speed (RPM) | Electromagnetic torque (N·m) | Comment |
|---:|---|---:|---:|---|
| 0.284 | `PWM_PAIR=8 mask=24` | — | — | First QEMU valid power pair, floating source phase U |
| 1.209 | `ROTOR` | +57.981 | +1.820 | Stator applies positive torque |
| 2.209 | `ROTOR` | +205.626 | +2.219 | Acceleration before first capture |
| 2.684 | `CMP_FILTER=U rising`, `CAP1` | — | — | First native comparator source threshold crossing; raw phase code **2049** vs DAC **2048** |
| 4.209 | `ROTOR` | **+416.856** | +0.654 | Positive peak in first drive pair |
| 5.209 | `ROTOR` | +384.579 | **−1.851** | Torque reversed **without changing six-pad power pair** |
| 6.209 | `ROTOR` | +179.807 | **−3.426** | Strong counter-torque |
| 6.671 | `CMP_FILTER=U falling` | — | — | Comparator source code back to 2048 (DAC=2048) |
| 7.209 | `ROTOR` | **−45.799** | −2.853 | **Mechanical speed reverses before next commutation** |
| 10.209 | `ROTOR` | −329.123 | +0.730 | Torque changes sign again, same pair |
| 12.209 | `ROTOR` | −6.084 | +2.677 | Rotor approaches zero again |
| 12.412 | `CMP_FILTER=U rising`, `CAP1` | — | — | Second U comparator rising crossing, same power pair |
| 15.051 | `TIMG12` | — | — | Source timer delayed step interrupt |
| 15.118 | `PWM_PAIR=2 mask=9` | — | — | First *actual* switched six-step pair after repeated speed reversals |

**Directly observed causal chronology:** The mechanical rotor changes sign while the original valid QEMU six-pad `PWM_PAIR=8` is still energized, *before* the next native `PWM_PAIR` occurs. The first sector has at least two U filtered rising comparator source events and two CAP1 events prior to first `TIMG12 -> PWM_PAIR` completion. This is **not concurrent boot music**: the source PWM audio-div32 mode ended at ~887ms; the positive demand began at 1500ms. This is also not a six-step *digital pair-order* inversion.

**Model-limited mechanism:** A fixed stator field, strong simulated phase current/torque, an assumed rotor-only inertia `J=0.00013kg·m²`, modeled BEMF and zero-cross timing are enough to produce angle/torque oscillation in the simulation. It does not prove that a real motor with a 24×12E propeller behaves this way. Comparator source codes at the zero-cross edge are 2048→2049 (just one 12-bit ADC count at the ideal 2048 threshold), and the synthetic analog gain/reference have not been calibrated against real hardware.

## Clock A/B completed: the same **first-sector torque inversion** persists at 200MHz

With **the same Original Rel17.3**, source DShot stages, initial electrical angle -30°, KV210 parameters and original P1, [MCPWM source-clock experiment run #41178746233](https://github.com/cctsao1008/escape32-qemu/actions/runs/41178746233) completed **both** 200MHz QEMU root-clock source-backed jobs. Effective read-only QEMU clock = 200MHz as requested in both, QEMU build and 5100 DShot frames PASS; **Original P1 FAIL** significant direction reversal in both.

Fresh source artifacts downloaded from that run and compared with the previous original 100MHz source artifacts. For each case, "first sector" means from the first authentic `PWM_PAIR=8` to the next `PWM_PAIR=2`; rotor angle delta uses `PWM_PAIR.d` (source native electrical angle) and `ROTOR.b` (unwrapped model electrical angle), not a Guest angle sensor.

| KV210 motor-only / MCPWM root | First valid pair after +20% input | Time to *next* pair | CAP1 source captures before next pair | First **negative** model torque sample | First RPM below -50 | Electrical displacement from pair start to negative torque | Electrical displacement to RPM below -50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 24V / historical 100MHz | +0.284ms | **14.834ms** | 2 | +5.209ms | +8.209ms | **154.0°** | 181.5° |
| 24V / source-corrected 200MHz | +0.220ms | **14.835ms** | 2 | +4.659ms | +7.659ms | **127.2°** | 193.0° |
| 47V / historical 100MHz | +0.284ms | **11.417ms** | 2 | +4.209ms | +6.209ms | **178.0°** | 184.3° |
| 47V / source-corrected 200MHz | +0.241ms | **11.376ms** | 2 | +3.804ms | +5.804ms | **151.9°** | 198.8° |

Times are milliseconds relative to each run's **first +20% source DShot event**, and "first negative torque" is the first sampled `ROTOR.f < -0.1 N·m`; "first RPM below -50" is the existing strict P1 significant speed sign threshold. The angle is an internal physical-*model* state and MUST NOT be used as an artificial Guest rotor signal. The first modeled electrical rotor excursion exceeds **120° before first negative torque**, versus the 60° spacing of conventional six-step sector transitions, but it is **not evidence of 120° physical hardware motion**.

**Narrow causal statement supported by actual source events:** in all four models, the first PWM power pair is held while the model electromagnetic torque changes sign and then the rotor speed reverses. The first motor source CAP1 occurs early, yet the next source PWM_PAIR is not emitted until >11ms (47V) or >14ms (24V) after the first pair. Two CAP1 events can occur in that same first sector because the rotor oscillates across the modeled comparator threshold. Merely correcting QEMU MCPWM clock from 100MHz to firmware-intended 200MHz does **not** resolve this first-sector behavior or unchanged P1 FAIL.

**Remaining unknowns:** why the Guest's first CAP1 is or is not accepted for commutation scheduling; exact comparator polarity/threshold/hysteresis, BEMF blanking, physical phase-to-sense wiring, source model current transient accuracy, blade inertia, and driver freewheel path. The result warrants *read-only* `CMP_FILTER→CAP1→CAP1_ACK→T12_LOAD→TIMG12→PWM_PAIR` and rotor-model angle alignment before changing either QEMU physics or firmware. Firmware behavior remains the immutable reference, not a debug target to patch for SITL. **Issue #5 OPEN.**

## Hypotheses to distinguish before considering firmware

1. QEMU **100MHz MCPWM source clock**, versus 200MHz MCLK-derived clock in original firmware: independently verified discrepancy, with separate opt-in A/B source-clock trial; retain QEMU old default.
2. Native **BEMF phase/neutral reference**: comparator threshold and mux are source-only approximations, and a one-code threshold event does **not** establish the hardware comparator hysteresis/blanking/analog propagation.
3. Incomplete **power-stage / freewheel / current** realism: idealized driver and R/L with high-current transients, no calibrated physical coil current limit, rotor inertia/propeller load uncertainty.
4. The original firmware's relative CAP1/TIMG12 timing is an **observable policy under simulation** but **not a bug** without independent confirmation that source model matches the hardware.

**Next evidence needed:** after 200MHz A/B runs finish, compare the same 0–20ms after first command: (1) time from first pair to torque sign reversal and rotor sign reversal; (2) CMP_FILTER/CAP1 repeated crossings before first TIMG12; (3) phase ADC/DAC code; (4) source duty/current/kinematic constraints. No firmware edit, oracle relaxation, or artificially injected physical feedback.

**Issue #5 OPEN.**
