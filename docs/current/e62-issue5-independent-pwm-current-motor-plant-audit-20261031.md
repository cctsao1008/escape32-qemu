# E62 Issue #5 — Independent PWM/Current/Motor Plant Source Audit

**2026-10-31 | SIM_ONLY | Original ESCape32 Rel17.3 unchanged | Strict Original P1 FAIL | Issue #5 OPEN.**

## Direct result

**The existing QEMU motor is internally consistent over the independently checked first-sector two-phase electrical regime; gross numerical error was NOT found.** A separate source-driven exact two-phase RL solution, using actual QEMU MCPWM AQ/DB output transition times (not guessed DShot duty, nor QEMU current as electrical input), independently reproduced its winding current. Motor-angle/torque and rotor kinetic-energy accounting also agree within source logging resolution.

**An actual *model initial-condition problem* was found:** the original ESCape32 motor-generated startup music rotates the SIM_ONLY rotor for alternative reset positions. The QEMU motor-only, uncalibrated viscous friction gives a 1.3-second coast time constant, so the modeled rotor is not stationary or at the configured reset angle by the time the first positive DShot command arrives. A -30° reset happens to remain at zero speed and fixed angle under these waveforms. **The -30° case is not representative of all possible rotor poses and residual speeds.**

## Immutable source and model provenance

- [Four actual Original Guest source CI runs](https://github.com/cctsao1008/escape32-qemu/actions/runs/41192708874): all strict P1 FAIL, with unwaived `STARTUP_SIGNIFICANT_DIRECTION_REVERSAL`.
- Original Rel17.3 ELF SHA256: `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`; 5,100 DShot600 source frames per case, unchanged Guest and Cfg policy, 24V KV210 motor-only, 200MHz QEMU MCPWM.
- [Independent source analyzer](https://github.com/cctsao1008/escape32-qemu/blob/experiment/e62-motor-plant-independent-validation-20261031/tools/e62_first_sector_reference.py) and [unit tests](https://github.com/cctsao1008/escape32-qemu/blob/experiment/e62-motor-plant-independent-validation-20261031/tests/test_e62_first_sector_reference.py) — mathematical tests PASS. Exact source focus: `1498:1520ms`, around 1700–1900 original six-pad AQ/DB switch events per case. No synthetic rotor, PWM, BEMF, CAP1, TIMG12 or Guest register writes.

## Independent electrical reference, genuine first 5ms

The observed first power sector is W-high / V-low with U floating; PWM goes W-low / V-low for synchronous low-side freewheel. **20% DShot command is NOT 20% high-side duty.** All cases show W-high/V-low for 13.689–13.798%, W-low/V-low for 84.67–84.78%, and about 1.53% transition/dead-time diode paths. This is actual source-mask timing, not inferred duty.

The independent winding-loop equation is: `L_LL*(diW/dt)+R_LL*iW = (VW-VV)-(eW-eV)`, with `R_LL=0.0566ohm`, `L_LL=17.5uH`, exact RL exponential per original PWM mask edge, real source theta/omega interpolated from 1ms ROTOR records, fixed QEMU diode 0.7V and source 24V VBUS. It uses neither the QEMU three-phase active-set solver nor QEMU current as input. **Only valid when source U-phase current is near zero.**

| Source case (24V) | First PWM pair dwell | Actual switch-focus events | Independent RL current mean abs error | Max abs error | Reduced two-phase scope |
|---|---:|---:|---:|---:|---|
| Sine reset -60° | 7.8343ms | 1,711 | 0.0484A | 0.0917A | 5 valid current samples |
| Sine reset -30° | 14.8350ms | 1,909 | 0.3437A | 0.5192A | 5 valid current samples |
| Sine reset +30° | 9.0427ms | 1,909 | 0.4204A | 0.4781A | First 3 samples only; U current thereafter invalidates reduced loop |
| Ideal trapezoid reset -30° | 14.2933ms | 1,735 | 0.3974A | 0.6857A | 5 valid current samples |

The separate torque reconstruction maximum error is 0.00119–0.00212Nm, and source e*i electromagnetic work agrees with independently derived rotor kinetic energy and viscous drag to 0.000011–0.000201J first-sector discrepancy, given 1ms source samples. **This is internal mathematical consistency, not real motor-current calibration.**

## New model source finding: startup sound alters actual rotor state

| Original QEMU model reset phase | Phase just BEFORE 20% DShot (mod 360°) | Mechanical rotor rpm before DShot | Max abs speed in initial 1500ms neutral/audio |
|---|---:|---:|---:|
| Sine reset -60° | +114.68° | -7.690rpm | 35.464rpm |
| Sine reset -30° | -30.02° | 0rpm | 0rpm |
| Sine reset +30° | -164.01° | +4.241rpm | 41.708rpm |
| Trapezoid reset -30° | -30.02° | 0rpm | 0rpm |

This does **not** mean audio PWM is active during the positive-demand window. Earlier sources show the /32 audio clock only during initial neutral. Instead, rotor motion from those actual PWM pulses persists into demand due to model mechanical coasting. At -60° and +30° the unchanged first W-high/V-low power pair produces negative torque from its **actual** initial rotor angle, unlike the quiet -30° case which starts with positive torque and later overshoots.

QEMU's physical source assumptions: `J=0.00013kg*m²`, assumed viscous `B=0.0001Nm*s/rad`, thus model coast `tau=J/B=1.3s`. From actual source at t=1199.83ms and 1499.83ms, independent inferred coast constants are **1.29947s (-60°)** and **1.30088s (+30°)**. Model coast behavior is numerically correct **under its own unverified friction assumption**.

## Decision / calibration limits

- QEMU reference-model numerical performance is not the demonstrated cause of reversal. Do not change J, R, L, Kt or friction only to obtain green P1; do not modify Original ESCape32.
- The QEMU **initial-condition methodology** is materially incomplete if it records only reset angle; any actual model audio-driven rotor angle and speed immediately before positive demand must be reported.
- The 0.7V ideal diode, no MOSFET resistance/DC-bus sag, phase saturation, unmeasured high-current torque, uncertain true BEMF waveform, motor-only load and `B=0.0001` friction are **not calibrated against Maxon EC87 hardware**.
- The physical decision requires matched safe startup measurements: PWM six-pad state / phase-current waveforms / actual BEMF crossing / rotor angle-speed just before command / motor-and-prop inertia or effective load. Then modify only supported model parameters and rerun Original strict P1.
- **DO NOT label internally consistent QEMU as hardware verified or accept a P1 result by suppressing motor audio or artificially resetting rotor before demand.** Keep the original firmware and P1 acceptance unchanged.

Official modeling reference: [MathWorks Simscape Electrical BLDC](https://www.mathworks.com/help/simscape-electrical/ref/bldc.html) specifies electrical winding voltages and offers ideal versus measured/tabulated BEMF; it does not prove the unmeasured Maxon EC87 shape or driver losses.

**Status: independent source-driven model cross-check supported (within constrained first sector); physical motor model calibration OPEN; Original P1 FAIL; Issue #5 OPEN.**
