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
