# E62 — Autonomous Motor-Coupled SITL Architecture Correction

**2026-10-27 | Direct-main implementation contract**

## Decision

The G17–G20 host-coupled WFI-stop → historical PWM replay → BEMF injection pipeline is **not** autonomous ESC–motor closed-loop SITL. The separate G13B5 autonomous DShot fixture uses synthetic timed BEMF rather than rotor-generated BEMF. These are both useful limited-scope tests, not substitutes for the requested behavior.

```text
Autonomous external DShot -> PA26/TIMG4/DMA -> unchanged ESCape32 Rel17 Guest
                                                |
                                                v
                 MCPWM4 actual AQ/DB/PB13/Trip switching -> Motor Plant
                                                                |
                                       Iabc, torque, theta, omega, BEMF
                                                                |
                           original Guest <- CMPSS0 <- U/V/W analog voltage
                                                  |
                                            ECAP1 / TIMG12
```

**No WFI breakpoints, no CPU stop, no GDB-driven plant stepping, no fixed artificial BEMF frequency.** All software-controlled and physical-simulation events advance on the shared QEMU Virtual Clock. Read-only diagnostics may sample but must never affect the model.

## Non-negotiable invariants

- Original Rel17.3 Guest ELF unchanged: `baseline/e62-g13b3/firmware/AM13E-rev17.3.elf` with SHA256 `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
- No Guest SRAM, IRQ, CAP1/TIMG12, MCPWM registers or commutation sequence writes by the host or model.
- Feed the motor from QEMU's original-clocked AQ/DB six-pad levels, gate state and Trip. Never substitute six-duty averages or guessed startup steps.
- Current continuity on phase switching, star constraints and explicitly modeled ideal-diode freewheel. Bounded integration and fail-closed invalid events or invalid physical values.
- Calculate electrical torque, mechanical speed and angle, and three-phase BEMF from the rotor model. Supply the three BEMF voltages through the CMPSS0 simulation analog interface on a native QEMU timer; no WFI wait or debugger intervention.
- Existing autonomous PA26 DShot timer may be reused. Rotor-derived BEMF and the preexisting synthetic autonomous BEMF generator must be mutually exclusive.
- Existing G14 (~20ns same-leg overlap) negative regression and G19 selected-input majority-filter rule remain. No Strict Gate waivers.
- The initial ECX87-KV147 profile is **SIM_ONLY, 24V, uncalibrated**. Not 12S, propeller, real board, MOSFET, GaN, thermals or physical hardware qualification.

## Stages and acceptance

1. **A: Native asynchronous plant wiring.** Add explicit opt-in motor component in QEMU, virtual-time physics timer, switching-event hook, source-generated BEMF, read-only counters, fail-closed state and mode arbitration. Ensure QEMU builds.
2. **B: Native Guest closed-loop source provenance.** Run unchanged Guest and autonomous PA26 DShot without CPU stops. Prove real PWM event → motor integration → real CMPSS filtered edge → original ECAP1 CAP1 → TIMG12 → next PWM sector.
3. **C: Physics verification.** Numerically compare continuous-current / diode behavior against the host reference, test energy and timestep convergence; do not tune to meet acceptance.
4. **D: Strict motor validation.** At least 12 original Guest CAP1/TIMG12/commutation sectors and 90ms, without significant rotor reversals; zero same-leg unsafe overlap, no missing PWM/gate provenance. A failed test remains failed.
5. **E: Board electrical and physical validation.** Actual BEMF sensing, propeller, driver, supply, protection, silicon timing and physical measurements remain OPEN.

## Historical evidence boundary

Previous WFI G20 diagnostics measured 35 WFI-bracketed model speed sign changes, including two before first accepted CAP1, and 23 significant post-six-sector reversals. Those values are historical diagnostic evidence **only**; they cannot certify an autonomous model. The previous 5ms startup early-capture hypothesis cannot be promoted to a validated root cause until the correct autonomous feedback timing is exercised.

## Development discipline

Commit directly to `main`, never use PR. Keep old host/WFI fixtures as clearly labeled historical comparators while implementing the new mode. Change of `machine/*.c` or `machine/*.inc` requires `./build.sh`, not just Python tests. No Host PASS may be represented as an original-Guest rotor stability PASS.

**Implementation status:** Incremental. Landing this document or source scaffolding is not itself evidence of a stable autonomous ESC–motor loop.
