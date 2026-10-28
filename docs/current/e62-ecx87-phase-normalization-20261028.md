# E62 maxon EC 87 flat UAV (KV147): terminal/phase normalization

Status: **mathematical convention corrected in QEMU source + host ECX87
profiles; native Original Guest P0/P1 outcome pending strict CI**.

## Primary source and unqualified assumptions

The user-supplied **maxon EC 87 flat UAV** datasheet, April 2025,
page 1, 773484 sensorless KV147 column:
24 V nominal, 3500 rpm no-load, 895 mA no-load, nominal
torque 1590 mNm at 2690 rpm and 22 A, terminal-to-terminal R
0.106 ohm, terminal-to-terminal L 0.048 mH, published Kt
64.9 mNm/A and Kv 147 rpm/V, mechanical tau 3.26 ms,
1300 g cm^2 inertia, 21 pole pairs, 3 phases, 6000 rpm max.

The datasheet **does not specify a phase-resolved sine BEMF waveform
or inverter gate-drive/switching model**. The source code below uses
an explicitly idealized **balanced star-connected sinusoidal flux**
phase model, with no propeller, no calibrated motor phase flux profile,
no saturation, and no qualified power electronics. This is **not**
a hardware qualification.

## The dimensional issue corrected

The published terminal-equivalent electrical back-EMF constant agrees
with the published mechanical speed constant:

```text
K_terminal = 0.0649 Nm/A (= equivalent V/(rad/s))
60/(2*pi*Kv) = 60/(2*pi*147) = 0.06496 V/(rad/s)
```

In the balanced sinusoidal phase model, with phase electrical offsets
`(0, -2*pi/3, +2*pi/3)`, the *maximum* line-to-line induced EMF is
`sqrt(3)*K_phase*omega_mechanical`; hence an equivalent terminal
constant cannot directly be installed as a per-phase sine coefficient:

```text
K_phase = K_terminal / sqrt(3)
        = 0.037470032470406714 (SI)

basis[p] = sin(theta_electrical + phi[p])
e[p]     = K_phase * omega_mechanical * basis[p]
T_e      = K_phase * sum(I[p] * basis[p])
d(theta_electrical)/dt = pole_pairs * omega_mechanical

=> sum(I[p] * e[p]) = T_e * omega_mechanical
```

Mechanical/electrical angular speeds are distinct: the formula
already absorbs the pole pair count in `theta_e` and does **not**
apply `pole_pairs` a second time to phase BEMF or torque.

At 3500 rpm, the old 0.0649 per-phase coefficient gave
`sqrt(3)*0.0649*(3500*2*pi/60) = 41.20045 V` max line EMF.
The converted value gives `23.78709 V` (approximately nominal
24 V, allowing for rounded datasheet constants and no-load losses).
The old value over-scaled the phase flux factor by `sqrt(3)`.
It did not violate internal power reciprocity when applied to both
BEMF and torque, **but it did violate the external maxon KV/terminal
electrical scale**.

Line-to-line R and L map to the balanced, magnetically uncoupled
phase equivalents `R_phase = 0.106/2 = 0.053 ohm`,
`L_phase = 48uH/2 = 24uH`. The datasheet mechanical time-constant
consistency check is
`J*R_LL/K_terminal^2 = 3.2716ms`, near 3.26ms.
These are equivalent-circuit approximations, not proof that mutual
inductance and phase saturation are absent.

## Modified program behavior

- `machine/am13e_native_motor_plant.inc`: declares unambiguous
  `AM13E_NATIVE_KT_TERMINAL` and `AM13E_NATIVE_K_PHASE`;
- `machine/am13e_native_motor_dynamics.inc`: uses `K_PHASE`
  for electromotive current coupling **and** electromagnetic torque;
- `machine/am13e_native_analog_frontend.inc`: BEMF synthesis uses
  exactly the same corrected phase coefficient;
- `tools/native_motor_model_profiles.py`: both KV147 and KV210
  host ECX87 profiles convert terminal Kt to per-phase sine
  coefficient and check Kt/Kv within 1%; historical `legacy`
  and `reciprocal` profiles remain unchanged;
- `tools/native_p1_pre_feedback_geometry.py`: new traces audited
  against corrected phase coefficient; `--historical-terminal-kt-as-phase`
  exists **only** for explicit pre-fix pinned archive replay.
  A previous run's events must **never** be silently reinterpreted
  as a run with the new model.
- `tests/test_e62_ecx87_phase_normalization.py` tests independent
  datasheet dimensional relationships, arbitrary three-phase
  electrical-to-mechanical power reciprocity, initial six-step
  torque geometry and the actual QEMU model's C symbols.

## What was NOT changed or proven

**No changes** to Original Rel17.3 ELF, Guest PWM table, original
hardware-facing BEMF phase routing, QEMU 1 us physical integrator,
voltage and current solver, motor load/friction, P0/P1 acceptance
rules, or archived pinned binary/manifest.

A corrected static physical scaling is NOT a proof that the Direct
20% startup reversal is fixed. In particular, if the original
fixed startup vector is held while actual rotor angle passes the
positive-torque interval, actual torque will still reverse in an
otherwise correct model. The available data does not prove whether
startup commutation timing, uncalibrated initial motor angle/load or
power-stage model differences are the dominant cause *after* scaling.

## Strict required validation

1. Host: `python3 tests/test_e62_ecx87_phase_normalization.py`;
   `python3 tests/test_sim_motor_profiles.py`;
   `python3 tests/test_native_p1_pre_feedback_geometry.py`.
2. Compile new QEMU source, verify Original ELF SHA256
   `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
3. Rerun unchanged native P0 strict, native P1 direct20/steps/ramp
   strict, rotor strict and independent energy/causality audits.
4. Retain failed cases and exact guest/source evidence without P1
   waivers or changing the historical pinned manifest.

Acceptance terms: *model dimensional consistency*,
*energy-reciprocal math*, *native physical source-causal pass*,
*P1 rotor stability* and *hardware motor validity* are separate
claims. **Do not promote one PASS into another.**


## 2026-10-28 post-fix strict CI: model consistency PASS, rotor P1 FAIL

The first compiled QEMU after normalization was verified at
[Native P1 #40713772648](https://github.com/cctsao1008/escape32-qemu/actions/runs/40713772648);
[Host CI #40713772643](https://github.com/cctsao1008/escape32-qemu/actions/runs/40713772643)
PASS. The **new 0.0649/sqrt(3) physical scale did not solve reversal**:

| Input | Current-model strict source result | Significant reversal events |
|---|---|---:|
| smoke | FAIL insufficient Guest closed-loop | 0 |
| gentle | FAIL insufficient Guest closed-loop | 0 |
| direct20 | FAIL direction reversal | 262 |
| steps | FAIL direction reversal | 174 |
| 100ms ramp | FAIL direction reversal | 186 |
| 500ms ramp | FAIL reversal and insufficient closed-loop | 5 |

Within Direct20, after the first **physical** W+/V- PWM pair
(+0.284ms relative to first positive DShot), a genuine first
CMPSS0/ECAP1 CAP1 occurs at +3.064644ms; but the first Guest
TIMG12 is only at +16.805796ms. The early rotor trace first records
negative torque at +6.209404ms and a reverse speed below -50rpm
at +9.209404ms. All times are QEMU virtual time relative to the
positive command. These are source-observed events, not approximated
host-injected commutations.

Independent ORIGINAL firmware source at pinned
ESCape32 commit `b0204670515d2de0b2480b52273038f1ee13d30a`
explains the delay. `src/main.c` directly initializes
`ival=10000 << MOTOR_TIME_SHIFT` on startup and the AM13E
port uses `MOTOR_TIME_SHIFT=0`; the unchanged Rel17 acceptance
condition `capture_ticks < (ival >> 1)` rejects early CAP1
crossings before 5000us. `motor_bemf.c` explicitly retains
ECAP1 arming after a rejected capture and only advances the
accepted-crossing epoch when the original callback accepts an edge.

The first CAP1 is 2.780800ms after the first powered PWM pair;
the next CAP1 is 13.779800ms after it. The second-to-first-TIMG12
delay is 2.742152ms. These timestamps are consistent with the
original 5000us startup rejection threshold and the later accepted
Rel17 programmed-commutation delay. **Direct CAP1 capture origin
and callback status are not independently present on each trace
event**, so do not claim a formally exact capture_us/accepted flag
based on event ordering alone.

### Isolated control-policy experiment (NOT Original Rel17)

An opt-in, separately compiled branch in
[cctsao1008/ESCape32](https://github.com/cctsao1008/ESCape32/tree/e62-sim-early-bemf-startup-20261028)
sets the **initial**, not timeout/desync, Rel17 `ival` to 4000us
under `AM13E_SIM_ONLY_EXPERIMENTAL_EARLY_BEMF` (default OFF).
This changes the early rejection threshold to 2000us.
[Separate firmware-build CI #40719585017](https://github.com/cctsao1008/ESCape32/actions/runs/40719585017)
**PASS** for both default and experimental ELF, confirmed different.
It does **not** establish a rotor PASS.

A separate
[QEMU controlled Direct20 A/B experiment](https://github.com/cctsao1008/escape32-qemu/tree/experiment/e62-early-bemf-direct20)
uses the same corrected motor physics and identical 3300-frame
virtual-clock Direct20 external FC source against separately compiled
default and experimental Guests. This is isolated from the
Original-Guest pinned ELF and strict P0/P1 Gate. Its outcome
is provisional until run evidence is reviewed.

Current conclusion: **phase-coefficient dimensional error corrected,
but the remaining first-step overshoot arises before the first
commutation and is consistent with the original startup BEMF acceptance
window being too long for a high-acceleration unloaded test case**.
Neither this experiment nor a future source-timing improvement is a
hardware safety or motor-stability qualification.
