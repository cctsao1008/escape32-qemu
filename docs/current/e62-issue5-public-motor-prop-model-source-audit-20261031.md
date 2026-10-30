# E62 Issue #5 — Public Motor/Propeller Model Source Audit (2026-10-31)

**Scope:** SIM_ONLY research and independent model-sensitivity analysis. **No firmware edit, no QEMU plant edit, no policy/oracle relaxation, no qualification claim.** Original Rel17.3 P1 and Issue #5's existing 300ms reversal failure are retained. Firmware is the device under test: do not alter its startup or windmill policy to make a SITL case pass. Only a separately proven firmware defect is a permissible basis for a firmware fix.

## 1. Source hierarchy and traceability

| Item | Source-backed fact | Current QEMU model | Qualification implication |
|---|---|---|---|
| maxon EC 87 flat UAV KV147 / KV210 | Published Kv = 147/210 rpm/V; line-line R = 0.106/0.0566 Ω; line-line L = 48/17.5 µH; terminal Kt = 0.0649/0.0454 N·m/A; 21 pole pairs; rotor J = 1300 g·cm² = 0.00013 kg·m² | Both profiles match these published constants under the explicitly assumed balanced-star/sinusoidal conversion | Source-backed **motor-only** reference; actual three-phase waveform, winding temperature, and motor + propeller loading are not thereby qualified |
| Simulated DC supply | Queen Bee customer baseline specifies 47 V at APC 24×12E, 12S4P | QEMU sets 24 V, fixed in native motor source and strict simulation profile | Historical 24 V tests may be valid as explicitly **24 V SIM_ONLY** tests; they are not 47 V / Queen Bee operating-point qualification |
| Aerodynamic rotor load | APC publishes **24×12E** analytically generated static performance, with thrust, shaft torque and power at specific RPM | QEMU torque balance has only a fixed viscous drag coefficient 0.0001 N·m/(rad/s); **propeller load torque = 0** | The 300ms coast mechanical trajectory can differ substantially for a powered-off **propeller-loaded** motor |
| Propeller inertia | Neither cited maxon motor page nor the APC aerodynamic performance data supplies a measured combined propeller/hub moment of inertia | Only bare-motor rotor inertia, no J_prop | Do not silently assign guessed J_prop or call the first prop-load sensitivity experiment calibrated |
| Analog front end | AM13E has three 12-bit ADCs with independently triggered SOC/SEQ structures; BEMF measurement depends on actual signal conditioning | 1.65 V bias; 0.02 V/V gain and 3.3 V, 12-bit conversion are explicitly simulator-only assumptions | Do not infer real ADC phase-separation margin from the idealized analog input, and do not confuse the 1kHz diagnostic log with actual Guest ADC acquisition |

### Original public sources

- maxon EC 87 flat UAV datasheet (Apr 2025), motor specifications p.1: https://www.maxongroup.com/assets/public/caas/v1/media/268812/data/f287362beea218093b20ee0365f2d037/drone-and-uav-propeller-28x9-4-data-sheet.pdf
- APC official analytical performance-data methodology: https://www.apcprop.com/technical-information/performance-data/
- **Exact APC 24×12E data, source version `v2022-0915`, simulation date 2022-09-22:** https://www.apcprop.com/files/PER3_24x12E.dat
- TI AM13E23019 device information: https://www.ti.com/product/AM13E23019
- TI sensorless startup stages, relevant as background only — not a mandate to modify ESCape32 firmware: https://software-dl.ti.com/mcu-sdk/esd/AM13E2X-SDK/26_01_00_03/exports/docs/docs/am13e230x/user_guide/chapters/solutions/am13e230x/motor_control/control_start_sequence.html

## 2. Explicit APC 24×12E zero-air-speed references

From the source's `V=0.00 mph` rows (APC **analytical estimates**, not measured Quanta/maxon bench data):

| Prop RPM | Torque N·m | Shaft Power W | Static Thrust N |
|---:|---:|---:|---:|
| 1000 | 0.132 | 13.829 | 3.882 |
| 2000 | 0.494 | 103.522 | 15.603 |
| 3000 | 1.085 | 340.777 | 35.332 |
| 4000 | 1.913 | 801.198 | 63.362 |

These source rows establish **material aerodynamic loading** over this domain, but do not tell us propeller inertia, whether the installed vehicle operates statically or with airflow, or how accurately APC's aerodynamic prediction matches the actual powertrain. **Do not substitute the APC 26-inch/maxon prop tables for the customer's APC 24×12E.**

## 3. Reproducible *sensitivity illustration*, NOT a firmware/model PASS

To show only how a missing load term changes *coast sensitivity*, take an **illustrative**, not observed, start-of-coast speed of `3000 rpm`; take QEMU's currently assumed `B = 0.0001 N·m/(rad/s)` and published motor rotor `J_m = 0.00013 kg·m²`. Fit a local quadratic static prop torque **only at 3000 rpm**:

```text
omega0 = 3000*2*pi/60                    [rad/s]
k = 1.085 / omega0^2 = 1.0993348425e-5 [N*m/(rad/s)^2]

motor-only:     J_eff dω/dt = -B ω
with APC term:  J_eff dω/dt = -B ω - k ω |ω|
J_eff = J_m + J_prop                     [not independently known]
```

For positive speed the idealized closed-form coast is `ω(t) = ω0 exp(-a*t)/(1+(b/a)*ω0*(1-exp(-a*t)))`, where `a=B/J_eff`, `b=k/J_eff`. **These calculations are not full motor + switch + propeller QEMU runs**, and `k` is a single-RPM quadratic fit to the official analytical data. They are not pass/fail acceptance thresholds.

| Effective inertia | Friction-only 300ms coast | APC-quadratic + friction 300ms coast |
|---|---:|---:|
| `1 × J_m` (J_prop=0, illustrative lower inertia) | ~2382 rpm | ~293 rpm |
| `2 × J_m` (illustrative) | ~2673 rpm | ~561 rpm |
| `5 × J_m` (illustrative) | ~2865 rpm | ~1120 rpm |

This large variation is **precisely why the existing 24V, zero-prop 300ms source failure must not be reinterpreted as proof of an ESCape32 firmware bug**, nor should a hypothetical loaded-coast PASS overwrite the existing FAIL.

## 4. What to do without touching firmware

1. **Keep the current 24V zero-prop QEMU baseline unchanged and labeled motor-only.** Retain Original Rel17.3 P1 negative criterion and 300ms reversal counterexample.
2. If a new product-representative profile is needed, create it **separately and opt-in**: exact motor (KV210), 47V, APC 24×12E *APC-analytical* static load interpolation, plus clearly parameterized `J_prop` sensitivity and aerodynamic conditions. Do not pretend its first run is calibrated.
3. Before any QEMU plant change, check source-level: actual unpowered/coast MCPWM six-pad behavior, DShot timing, coupled terminal currents, ADCSOC/EOC/Guest ADCRESULT values, CMPSS filtered zero-crossing, CAP1/TIMG12 provenance, and rotor angle/torque only as read-only *host* diagnostics. No host Guest-register writes or leaked model rotor angle to firmware.
4. Gate both profiles separately under identical **unchanged Guest firmware and P1 oracle**; publish a failure matrix for 300/1500/3000ms, independent initial electrical phases, KV147 and KV210 where applicable. A counterexample remains FAIL; parameter selection alone cannot close a failed feature.
5. Diagnose historical firmware integration CI failures independently; **no changes to the firmware as a workaround**. A real firmware bug requires evidence independent of making SITL green.

## 5. Current verdict

- **Issue #5:** OPEN. Existing 300ms restart reversal is a real failure in its stated 24V, unloaded, SIM_ONLY model; general applicability to 47V/propeller loading is **not established**.
- **Issue #7:** already CLOSED for its explicitly modeled running protection sources; this research does not reopen it.
- **Firmware changed:** NO.
- **QEMU dynamics/config changed:** NO.
- **New QEMU closed-loop qualification CI run:** NONE from this research note.
