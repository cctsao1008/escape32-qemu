# E62 Issue #5 — Original Guest / 47 V APC 24×12E Source-Plant Study

**2026-10-31 | branch-only SIM_ONLY experiment | NOT hardware signoff | NOT firmware bug claim | NOT P1 waiver**

## Strict boundary

- Firmware tested: unchanged pinned Original ESCape32 Rel17.3, ELF SHA-256 `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
- Do not edit ESCape32 firmware merely to pass QEMU/SITL. Only separately proven firmware defects justify firmware changes.
- `main` historical QEMU `ecx87-kv147`/`ecx87-kv210` remain **24 V, no propeller load** with identical original physical source path and unchanged P1 strict criteria.
- New product study lives on `experiment/e62-apc24x12e-47v-coast-20261031`, no implicit default opt-in.
- The current **300 ms actual model source failure** remains a FAIL for its baseline model. This study does not relabel it a firmware defect and does not replace it with a green synthetic result.

## Manufacturer evidence and explicit assumptions

1. Maxon EC87 KV210: published 210 rpm/V, `R_ll=0.0566 Ω`, `L_ll=17.5 µH`, terminal `Kt=0.0454 N·m/A`, 21 pole pairs, rotor inertia `J_m=0.00013 kg·m²`. Phase conversion and torque/BEMF reciprocity remain as in the existing QEMU plant.
2. Queen Bee requirement: **47 V DC bus**, APC **24×12E** (this is the *customer operating point*, not an assumed maximum absolute battery voltage).
3. APC manufacturer analytical static source `PER3_24x12E.dat`, version `v2022-0915`, simulation date `2022-09-22`, *only 0.00 mph rows*: 

   | RPM | Torque (N·m) | Thrust (N) |
   | ---: | ---: | ---: |
   | 1,000 | 0.132 | 3.882 |
   | 2,000 | 0.494 | 15.603 |
   | 3,000 | 1.085 | 35.332 |
   | 4,000 | 1.913 | 63.362 |
   | 5,000 | 2.996 | 100.138 |
   | 6,000 | 4.362 | 146.307 |

   The data are vendor **analytical predictions**, not Quanta motor bench measurements or reverse-windmill data.

4. Propeller/hub inertia **not available** in the above public sources. Run exact bounded *illustrative* inertia ratios `J_total/J_motor ∈ {1, 2, 5}`: this means respectively `J_prop/J_motor = 0, 1, 4`. **None is physically calibrated**; `J1` is a motor-only inertia sensitivity floor even though aerodynamic torque is present.
5. APC static torque is interpolated linearly between supplied 1000…6000 RPM points. Between 0 and 1000 RPM only, the model uses a quadratic extension matched to the 1000 RPM source; **this is an assumption**. Speeds above 6000 RPM are rejected (except a numerical epsilon at exactly 6000), not extrapolated.
6. Negative rotor RPM uses a sign-symmetric *resisting torque* extension. APC's forward static data **does not establish the actual reverse-running blade aerodynamics**. Therefore reversal occurrence remains an observable failure, but exact reverse recovery duration/torque is not hardware-calibrated.
7. Viscous friction coefficient `B=0.0001 N·m/(rad/s)`, `Vbemf = 1.65 + 0.02*E_phase`, idealized star motor, diode, 12-bit 3.3 V ADC and no thermal/forward-flight dynamics remain **simulation assumptions**.

Sources:
- https://www.apcprop.com/files/PER3_24x12E.dat
- https://www.apcprop.com/technical-information/performance-data/
- Project baseline `Queen_Bee_Customer_Requirements_Baseline.md`
- Project maxon datasheet `drone-and-uav-ecx-87-flat-uav-data-sheets.pdf`, p.1

## Exact opt-in profiles and readback

| QEMU machine name | Bus (mV) | J_total kg·m² | Interpretation |
| --- | ---: | ---: | --- |
| `ecx87-kv210` | 24000 | 0.00013 | unchanged, no propeller |
| `ecx87-kv210-apc24x12e-47v-j1` | 47000 | 0.00013 | static APC load, zero *additional* prop J |
| `ecx87-kv210-apc24x12e-47v-j2` | 47000 | 0.00026 | APC load, assumed `J_prop=J_motor` |
| `ecx87-kv210-apc24x12e-47v-j5` | 47000 | 0.00065 | APC load, assumed `J_prop=4*J_motor` |

QEMU read-only model observation window (host QTest, **never a Guest-accessible rotor sensor**): historical Kv/R/L/Kt/VBUS offsets `0x8c..0x9c` unchanged; new `0xcc` APC enabled flag, `0xd0` total inertia (nano kg·m²), `0xd4` last signed prop torque (µN·m), `0xd8` J multiplier. Old offsets are preserved; command parser rejects unsupported profile names.

## What gets tested

- New independent host test rejects malformed/weakened profile, wrong APC table, invalid torque/RPM, unsupported >6000 RPM extrapolation. Includes regression against original 24 V profiles.
- Source QEMU machine build; real Original Guest ELF; 1kHz external DShot scenario `e62-experimental-two-demand-coast-short300.json`; *actual* MCPWM PWM/AQ/DB -> phase current/torque/rotor -> ADC/BEMF/CMPSS/CAP1/TIMG12.
- QTest reads **effective** profile data; no model theta/RPM fed back into Guest, no Host Guest-register writes, no GDB/WFI stopping.
- Run strict existing Original P1 evaluator even if a negative result emerges; emit and archive raw source events, QEMU logs, readback and verdict.
- Separate future 1500ms and 3000ms scenario extensions **must use the same original ELF and original P1**, and account for runtime/performance before inferring phase/torque causality. Initial 300ms J sweep **does not qualify** all coast scenarios.

### CI

[Source study GitHub Actions workflow](https://github.com/cctsao1008/escape32-qemu/actions/workflows/e62-apc24x12e-47v-sim-only.yml). A green host source-contract job means only profile/model validation. The real QEMU motor functionality and restart P1 outcomes are **separate** and may FAIL.

## Closure criteria — not met by this model addition

Issue #5 must remain OPEN until source-backed first/coast/second-demand re-acquisition passes the unchanged Original P1 across the declared scenarios without rotor reversal; no product profile may authorize a Guest firmware rearm, fake an angle sensor, or reinterpret an unexpected reverse as PASS. **Neither simulated threshold tuning nor any unverified aerodynamic assumption can justify a firmware edit.**
