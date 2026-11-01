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
