# E62 Issue #5 — Maxon EC87 Datasheet Static Lock and Native QEMU Acceleration Audit
**2026-10-31 | SIM_ONLY | Original Rel17.3 unchanged | strict Original P1 FAIL | Issue #5 OPEN.**

## Decision
**No J/Kt/R/L unit or gross motor acceleration calculation defect found.** The first-sector overshoot is consistent with **datasheet rotor-only inertia and source-current torque**. However, the true acceleration error relative to physical hardware is **not identifiable without matched phase-current / speed measurements**. This is **static datasheet parameter calibration only**, not a qualified dynamic model.

## Source
- User-supplied `drone-and-uav-ecx-87-flat-uav-data-sheets.pdf`, Maxon EC87 flat UAV, April 2025, **page 1**.
- Original firmware SHA256: `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
- 24V/100MHz first-party [run #41178267331](https://github.com/cctsao1008/escape32-qemu/actions/runs/41178267331); 24V/200MHz and 47V/200MHz [run #41178746233](https://github.com/cctsao1008/escape32-qemu/actions/runs/41178746233); 47V/100MHz [run #41109233164](https://github.com/cctsao1008/escape32-qemu/actions/runs/41109233164).
- Read-only source reconstruction: 5,100 contiguous source-owned DShot600 frames each; actual six-step `PWM_PAIR=8 -> PWM_PAIR=2`, CAP1 and one-shot timer events; 1ms first-party QEMU rotor/current/torque source samples. No host Guest injection, altered firmware or P1 waiver.

## EC87 model parameter cross-check

| Spec, datasheet p.1 | KV147 | KV210 | Native plant |
|---|---:|---:|---|
| Pole pairs | 21 | 21 | matches |
| Rotor J (kg·m²) | 0.000130 | 0.000130 | matches |
| Terminal Kt (N·m/A) | 0.0649 | 0.0454 | matches named profile |
| Line-to-line R (Ω) | 0.106 | 0.0566 | phase R = Rll/2 |
| Line-to-line L (µH) | 48.0 | 17.5 | phase L = Lll/2 |
| Datasheet mechanical tau (ms) | 3.26 | 3.57 | J Rll / Kt² = 3.272 / 3.570ms |
| Maximum continuous current (A) | 22 | 33.4 | **NOT instantaneous I clamp** |
| Maximum continuous torque (N·m) | 1.59 | 1.70 | **NOT instantaneous T clamp** |
| No-load speed @24V (rpm) | 3500 | 4990 | Kv·24 ≈3528 /5040 |

Kv-derived Kt = 60/(2πKv) and mechanical tau = J·Rll/Kt² independently agree within published data rounding. `J=1300 gcm²=1.3e-4 kg·m²` is correctly converted in the plant. This validates source **static motor constants**, not peak-current dynamics or phase waveform.

**Important inconsistent/high-current data convention:** The datasheet lists nominal-24V stall torque/current KV147 = 5.38 N·m/227 A and KV210 = 5.97 N·m/424 A. The simplistic Kt·Istall calculation gives 14.73 /19.25 N·m — **not equal**. Source data do not clarify the necessary high-current / winding waveform / terminal current convention. Do not silently fit a fictitious hard torque cap or claim the QEMU linear high-current extrapolation has been calibrated.

## Source acceleration / rotor electrical-angle audit

| KV210 no prop | QEMU θ_e first crosses +90°, relative to initial 20% demand | Duration of unchanged first six-step power pair | Max abs sampled phase current in first pair | Maximum sampled |α|, 1ms finite difference |
|---|---:|---:|---:|---:|
| 24V, 100MHz historical | 4.56ms | 14.83ms | 80.0 A | ≈22.5 krad/s² |
| 24V, 200MHz opt-in | 4.52ms | 14.84ms | 78.4 A | ≈22.8 krad/s² |
| 47V, 100MHz historical | 3.42ms | 11.42ms | 148.6 A | ≈42.6 krad/s² |
| 47V, 200MHz opt-in | 3.39ms | 11.38ms | 140.8 A | ≈42.5 krad/s² |

At source-model electrical angle >90° under `PWM_PAIR=8` (W-high, V-low, U floating), torque goes negative even without a reversed PWM command. The 1ms sample finite-difference acceleration is comparable in order to source-model `T/J` but insufficient to certify its 1µs integration accuracy. Root-clock 100→200MHz does not materially alter first-sector overshoot.

At **Maxon's actual maximum continuous KV210 torque 1.70 N·m**, the ideal *constant-torque rotor-only* time from −30° to +90° electrical (120°) is already ≈**3.91ms**, versus 11–15ms source-observed first-sector wait. This only illustrates plausible overshoot; it does **not** prove the 20% DShot command supplies constant nominal torque in a real ESC.

QEMU observed first-sector phase currents are 2.35–4.45× the **maximum continuous** KV210 current 33.4A, but for only milliseconds. Continuous thermal limits are not instantaneous absolute current limits; at high current the QEMU R/L, sinusoidal Kt, ideal driver/diode and analog gain remain **uncalibrated**. The 47V experiments are also above Maxon's **nominal** 24V data.

A generous (but **not justified as a physical fit**) equivalent viscous drag `b≈0.000142 Nm·s/rad` from the *whole* KV210 1.63A no-load current would differ from current QEMU `b=0.0001` by only ≈0.0018–0.0027Nm over these first-sector RPMs, tiny relative to sampled 1–6Nm torque. Friction cannot plausibly explain the bulk of overshoot under this approximation.

## Calibration status / next action

- **Matched with manufacturer within given conventions:** rotor J; pole pairs; Kt/Kv; line-line R/L; derived mechanical time constant.
- **Not hardware calibrated:** actual source startup phase-current waveform, inverter MOS/gate/drop/saturation and active-current limit, phase BEMF ADC scale/bias/filter/hysteresis, actual rotor/load inertia, physical propeller loading, initial electrical pose, actual first CAP1 timing.
- **Assessment:** Nothing supports changing J, Kt or R/L simply to make Original P1 pass. An absolute claim of *overestimated QEMU acceleration* is **not supported** by the datasheet alone.
- **Engineering next step:** obtain a **matched safe 24V no-prop startup scope capture** of voltage, phase current, speed/electrical position or BEMF timing, PWM first-pair duration and CAP1-to-TIMG12 delay, plus ESC FW/demand. Use measurement to identify real current/flux/saturation and analog parameters; only then make physical-model edits. Re-run **unchanged Original P1**. 47V requires its own qualification rather than assuming nominal 24V motor characteristics scale linearly.
- **Do not change Original firmware, inject rotor state, or waive sign reversal to obtain green CI.**

Issue #5 **OPEN**; this is a **static datasheet source calibration**, not a motor acceleration hardware certification.
