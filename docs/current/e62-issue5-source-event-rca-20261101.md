# E62 Issue #5 — First-event analysis from archived native QEMU artifacts (2026-11-01)

## Source and qualification
Retrieved **actual** run [41291196333](https://github.com/cctsao1008/escape32-qemu/actions/runs/41291196333) artifact ZIPs, not summary-only PR prose:
- `13077122878` — 24 V / 300 ms coast / −30° **PASS**
- `13077671845` — 24 V / 1500 ms coast / −30° **FAIL**
- `13077552641` — 47 V / 300 ms coast / −30° **FAIL**

Parsed each `*.p0.events.log` with its original `*.json` and `*-candidate-metrics.json`. Candidate SHA256 `c82489dbc0c648d9e7a1cfd56560f88393a3bd4f56666a0e3df40d3bc598b2e6`. Original ELF remains unchanged and Original P1 is FAIL. Native source QEMU is SIM_ONLY and the EC87 KV210 plant is unloaded/uncalibrated.

## Evidence, event times relative to each DShot demand

| Case / demand | Demand begins | First source PWM_PAIR | First source CAP1 | First TIMG12 | First sampled RPM < −50 | Min RPM |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 24 V 300 ms, demand 1 | 1500 ms | +0.267 ms | +2.699 ms | +3.328 ms | none | +20.238 |
| 24 V 300 ms, demand 2 | 3300 ms | +0.267 ms | +0.770 ms | +0.917 ms | none | +45.701 |
| 24 V 1500 ms, demand 1 | 1500 ms | +0.267 ms | +2.699 ms | +3.328 ms | none | +20.238 |
| 24 V 1500 ms, demand 2 | 4500 ms | +0.267 ms | +6.073 ms | +8.317 ms | **+1.836 ms** | −344.114 |
| 47 V 300 ms, demand 1 | 1500 ms | +0.267 ms | +2.120 ms | +2.604 ms | **+20.830 ms** | −673.868 |
| 47 V 300 ms, demand 2 | 3300 ms | +0.267 ms | +4.777 ms | +14.352 ms | **+1.831 ms** | −516.549 |

`ROTOR.a` is milli-RPM; threshold is <−50,000 milli-RPM. Event logging sample cadence is finite, so first sampled threshold crossing is not exact physical crossing. Event timestamps are QEMU virtual nanoseconds; comparisons use first event at/after the scenario's absolute demand start (not inferred from arbitrary `ROTOR` scan windows).

## New causal distinction
1. **Pre-feedback torque / phase initialization is the first priority** for 24 V long-coast restart and 47 V second start: the rotor has already gone below −50 RPM well before the *first* source CAP1/TIMG12. Changing only CAP1 interval smoothing cannot prevent these earliest reversals. Examine `oldstep`, first six-step PWM vector, residual rotor angle/direction, phase mapping, and open-loop re-acquisition permission.
2. **47 V first-demand is different:** valid CAP1/TIMG12 occurs at +2.12/+2.60 ms, yet significant negative RPM appears at +20.83 ms. This requires a *post-feedback* analysis: compare successive electrical sector/actual torque sign, CAP1 polarity/phase, blanking and timing advance, and plant integration. It cannot be wholly attributed to an absent first capture.
3. The prior experimental PR's `sync<6`, capture 400–4500 us fast path is **not qualified** as a general fix. Do not merge/flash, relax P1, or alter plant constants to force PASS.

## Next discrimination gate
For each failing demand, extract the **first physical PWM sector/phase-to-phase command, actual rotor electrical angle, signed electromagnetic torque, actual CMPSS transitions, and exact accepted/rejected CAP1** within the first 25 ms, and compare to a passing same-ELF 24 V control. Attribution:
- phase/torque mismatch before first CAP1 = firmware startup initialization/algorithm or plant phase model (compare source mapping before deciding which);
- mismatch only after accepted CAP1/TIMG12 = ZC/commutation/handoff timing path;
- missing valid comparator edge in low BEMF = observability/re-acquisition design limit or analog/model defect, not automatically a firmware bug.

No firmware or QEMU plant changes were made in this evidence analysis; Issue #5 remains OPEN.


## Completed eight-artifact first-event sweep

Retrieved all eight separate CI artifact ZIPs from run `41291196333` (original archive entries `*.p0.events.log`, `*.json`, `*-candidate-metrics.json`) and parsed source event timestamps. All three previously documented cases remain consistent. Times are relative to the relevant DShot demand start.

| Case | Demand | First PWM_PAIR ms | First CAP1 ms | First TIMG12 ms | First rotor < −50 RPM ms | Demand min RPM |
|---|---|---:|---:|---:|---:|---:|
| 24V 300ms −30° PASS | first | 0.267 | 2.699 | 3.328 | none | +20.238 |
| 24V 300ms −30° PASS | second | 0.267 | 0.770 | 0.917 | none | +45.701 |
| 24V 1500ms −30° FAIL | second | 0.267 | 6.073 | 8.317 | **1.836** | −344.114 |
| 24V 3000ms −30° FAIL | second | 0.267 | 6.075 | 8.320 | **2.838** | −344.090 |
| 47V 300ms −30° FAIL | first | 0.267 | 2.120 | 2.604 | **20.830** | −673.868 |
| 47V 1500ms −30° FAIL | first | 0.267 | 2.120 | 2.604 | **20.830** | −670.850 |
| 47V 3000ms −30° FAIL | first | 0.267 | 2.120 | 2.604 | **20.830** | −673.868 |
| 24V 300ms −60° FAIL | first | 0.517 | 1.083 | 1.247 | **1.848** | −334.723 |
| 24V 300ms +30° FAIL | first | 0.267 | 1.170 | 1.417 | **1.830** | −216.026 |

For completeness, second demand at 47V/300ms becomes <−50RPM **+1.831ms** before first CAP1 **+4.777ms**; 47V/1500ms second demand crosses <−50RPM **+7.831ms** after first CAP1 **+3.559ms**; 47V/3000ms second demand crosses at **+1.833ms** after CAP1 **+0.838ms**. First negative time is a sampled crossing; no motor/prop qualification.

### Fault-class consequences
- **Pre-CAP1 reversal:** 24V/1500, 24V/3000, 47V/300 second demand. Changing a CAP1 interval filter **cannot by itself correct the torque command which precedes that first event**. Investigate first PWM sector and residual rotor angle/speed, open-loop startup, stale `oldstep`, and QEMU torque phase orientation.
- **Post-CAP1 reversal:** all 47V first demands and ±angle first demands; requires physical angle/torque-to-sector correlation and sensing/handoff analysis. A CAP1 occurrence is not a proof of correct rotation lock.
- **Mixed second-demand behavior:** 47V/1500 and 47V/3000 must remain distinct, not lumped with 24V long-coast.

No verified Firmware-only fix follows from RPM/event ordering alone. Core Firmware vs QEMU motor-phase-model attribution awaits matched electrical-angle and signed torque evidence. The v2 Candidate 1/8 outcome remains blocking.

## 2026-11-01 second-stage raw event alignment

The complete eight-artifact CI run `41291196333` was parsed into a local 1,839-row CSV covering the first 25 ms of each first/second demand. Preserved **uninterpreted original** six raw QEMU event payload fields `a..f` and event types `ROTOR`, `PWM_PAIR`, `CAP1`, `TIMG12`, `BEMF_FRONTEND`, `SWITCH_CURRENT`. Avoid assigning physical torque units to raw fields without verifying the QEMU emitter implementation.

Focused examples:

| Source event | 24 V / 300ms PASS second demand | 24 V / 1500ms FAIL second demand |
|---|---|---|
| First `PWM_PAIR` | +0.267 ms, a=4 b=6 | +0.267 ms, a=4 b=6 |
| First `ROTOR` sample | +0.836 ms, raw RPM=+45.701, raw angle=3912701 | +0.836 ms, raw RPM=−3.321, raw angle=3958517 |
| Second `ROTOR` sample | +1.836 ms, +155.738 RPM, raw angle=3912905 | +1.836 ms, −85.268 RPM, raw angle=3958429 |
| First `CAP1` | +0.770 ms | +6.073 ms |
| First `TIMG12` | +0.917 ms | +8.317 ms |

**Inference supported:** the initial source PWM_PAIR payload matches while rotor phase differs by 45,816 raw angle units (do not convert to electrical degrees without QEMU format verification). The failing case produces significant reverse RPM before any accepted CAP1; merely adjusting post-capture ival cannot repair that first interval. This is *not yet proof* of a firmware bug because the motor/torque phase mapping may be wrong. Need QEMU emitter raw-field interpretation and torque sign validation from actual source.

47 V first demand: CAP1 +2.120 ms, TIMG12 +2.604 ms, first sampled negative beyond −50 RPM +20.830 ms; a different downstream mode requires subsequent commutation/torque alignment. All eight cases still 1 PASS/7 FAIL; no firmware revision claimed.

## 2026-11-01 source-verified decoded torque evidence

QEMU emitter verified in `machine/am13e_native_motor_plant.inc` (`am13e_native_motor_tick`): `ROTOR` event payload is **(a)** mechanical RPM ×1000, **(b)** unwrapped electrical theta [radians] ×1000, **(c,d,e)** three phase currents [A] ×1000, **(f)** electromagnetic torque [N·m] ×1000000. This is actual native plant output, not an estimated torque reconstructed from RPM.

In `machine/am13e_native_pwm_coupling.inc`, `PWM_PAIR` is `(1+3*hi_phase+lo_phase, newmask, gate_word, theta_unwrapped×1000, zero_events, 0)`. Phase index 0=U, 1=V, 2=W. First paired sector is a physical source observation; not a firmware callback count.

| Same source Candidate v2 scenario (demand) | First PWM_PAIR (pair,mask) | First sampled phase angle (wrapped electrical deg) | First sampled actual torque [N m] | First sampled RPM | Status |
|---|---|---:|---:|---:|---|
| 24V/300ms/−30° (second) | (4,6) | 261.254° | **+0.937133** | +45.701 | PASS |
| 24V/1500ms/−30° (second) | (4,6) | 6.317° | **−0.658305** | −3.321 | FAIL |
| 24V/3000ms/−30° (second) | (4,6) | derived from preserved source event | **−0.328172** | −3.675 | FAIL |
| 47V/300ms/−30° (first) | (8,24) | initial phase near −30° | **+1.934482** | +39.935 | FAIL later |
| 24V/300ms/−60° (first) | (8,24) | source observed | **−0.284498** | −10.562 | FAIL |
| 24V/300ms/+30° (first) | (8,24) | source observed | **−1.078666** | −18.209 | FAIL |

The 24V 1500ms coast case has the **same** initial phase command `PWM_PAIR=(4,6)` as 300ms PASS but opposite source-computed torque sign. Its first sampled angular velocity is already negative ~0.836ms into second demand. Its first CAP1 is +6.073ms. Thus the initial adverse torque cannot be caused by a *later* CAP1 interval filter decision. It is consistent with a restart policy that reuses a predetermined sector without phase detection; confirm FW initial `step=oldstep; nextstep()` and observe the QEMU plant's angle convention before categorizing defect vs limitation. Motor dynamics source `machine/am13e_native_motor_dynamics.inc` evaluates `T=K_phase*sum(i_phase*sin(theta_e+offset))`, and updates omega using `J=0.00013 kg m²` (SIM_ONLY uncalibrated).

At 47V/300ms first demand, actual torque goes **negative around +9.830ms (−6.182 Nm)** and again around **+13.830ms (−7.511 Nm)**, long after first CAP1 +2.120ms / TIMG12 +2.604ms. Sampled rotor becomes negative RPM at +20.830ms. This supports an *independent post-feedback torque-sign / sector-timing instability*, rather than solely no-feedback startup.

Decoded 400 `ROTOR` samples across eight cases×two demands×25ms. Preserve caveats: event cadence 1ms; PWM switching much faster; rotor phase model and load not calibrated; torque values are **simulated plant torque**, not actual measured motor torque. Candidate remains 1 PASS / 7 FAIL, SIM_ONLY only. **No firmware change authorized merely by the sign of uncalibrated simulated torque.**

## 2026-11-01 47V first-demand first post-feedback loss-of-torque — precise QEMU event times

Source ZIP: run `41291196333`, artifact `13077552641`, `47v-300-m30.p0.events.log`. QEMU virtual timestamps below are demand-relative (absolute demand t=1500ms), original `E62_P0_EVENT` fields retained.

| event | t relative demand | details |
|---|---:|---|
| CAP1 | +8.046868 ms | phase b=1 |
| TIMG12 | +8.152068 ms | c=10399 |
| PWM_PAIR | +8.184778 ms | pair=8 mask=24 |
| CAP1 | +8.451876 ms | phase b=0 |
| TIMG12 | +8.554040 ms | c=10099 |
| PWM_PAIR | +8.559848 ms | pair=2 mask=9 |
| CAP1 | **+8.831876 ms** | phase b=2; no immediately corresponding TIMG12 in event log |
| ROTOR | +8.829636 ms | +1234.618 RPM, +0.870003 N m (sample slightly before CAP1) |
| ROTOR | **+9.829636 ms** | +1162.624 RPM, **−6.182254 N m**, pair remains 2 |
| ROTOR | +10.829636 ms | +772.603 RPM, +0.073844 N m, pair remains 2 |
| CAP1 | +11.667876 ms | phase b=2 |
| TIMG12 | **+12.473040 ms** | c=80399 |
| PWM_PAIR | +12.518710 ms | pair=3 mask=33 |
| ROTOR | +13.829640 ms | +673.849 RPM, **−7.511136 N m** |

**Observed fact:** following source CAP1 at +8.831876ms, no source TIMG12/PWM_PAIR was emitted until +12.473040/+12.518710ms. The ~3.641ms no-commutation interval overlaps first large negative simulated torque. CAP1 is a QEMU peripheral event, **not** independently proof that Guest application accepted crossing; need inspect `captured_events/rejected_events`, `sync/ival`, ECAP1 IRQ and TIMG12 timer programming or add source-owned diagnostics. Do not conclude timer malfunction from CAP1 alone. Compare with 24V PASS with same firmware/source model and evaluate intentional `capture < ival/2` rejection, missed IRQ or delayed timer schedule. Exact torque is SIM_ONLY uncalibrated model. Keep Issue #5 OPEN and Draft PR unmerged.
