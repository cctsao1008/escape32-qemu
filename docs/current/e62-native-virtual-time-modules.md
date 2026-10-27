# E62 — Native QEMU single-virtual-clock modularization

## Decision

**Separate PWM detection, continuous-current motor dynamics and analog feedback
into distinct source modules; do NOT create separate host OS threads.**

This is a **pure source-layout refactor** at the fixed 2026-10-28 baseline.
The guest remains the original ESCape32 Rel17.3 pinned ELF, SHA256
\`05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0\`.
No WFI or GDB, no Guest memory/IRQ/PWM control, no synthetic BEMF, no CLI.

## Ownership and clock domain

| Component | File | Responsibility |
| --- | --- | --- |
| Original virtual MCPWM4 hardware | \`machine/am13e_pwm_history.inc\` | Clocked AQ/DB six-pad physical mask and timestamped PWM events. Existing interface is unchanged. |
| PWM → motor coupler | \`machine/am13e_native_pwm_coupling.inc\` | Advance the OLD motor switch state to the exact source PWM event timestamp, reject invalid/overlapping gates, then latch the NEW mask. Own PWM_PAIR / bounded SWITCH provenance. |
| Motor differential equation | \`machine/am13e_native_motor_dynamics.inc\` | Phase current-continuous three-phase star/diode active-set solver, electrical energy identity, torque, unwrapped electrical angle, mechanical RPM. Physics constants and update order unchanged. |
| Native analog / BEMF frontend | \`machine/am13e_native_analog_frontend.inc\` | Convert current physical rotor angle/speed into 3-phase BEMF codes, publish atomically to existing CMPSS0 analog path; independently publish uncalibrated current sense to native OC comparator. |
| Existing silicon feedback | \`machine/am13e_motor_feedback.inc\` | CMPSS0 selected-phase comparator/filter, ECAP1 CAP1 capture, Guest IRQ. Original hardware routing unchanged. |
| Coordinator / observer | \`machine/am13e_native_motor_plant.inc\` | Original 1µs QEMU virtual-timer tick, source event trace, lifecycle/reset, read-only SIM_ONLY observer. Includes three single-TU source modules. |

All code executes on the existing **QEMU_CLOCK_VIRTUAL** event loop.
These \`.inc\` files do **not** imply C11 threads, host OS scheduling, mutexes,
or asynchronous concurrent access.

### Source causal sequence (unchanged)

1. Original Guest MMIO/shadow and virtual PWM clock update the AQ/DB state.
2. \`am13e_pwm4_hist_refresh\` invokes \`am13e_native_motor_pwm_event\` with the real six-pad mask.
3. Coupler integrates OLD switch state until the same virtual timestamp;
   then atomically latches NEW switch state, retaining the old phase currents.
4. The native 1µs periodic motor callback integrates the continuous phase
   currents, unwrapped rotor electrical angle, torque and speed.
5. Analog publication uses the *actual* modeled rotor to compute BEMF,
   and the already-existing CMPSS/ECAP/TIMG12 path schedules source-owned
   captures, filtered edges and Guest interrupts. The Guest itself decides the
   next PWM sector.
6. Original source-owned \`E62_P0_EVENT\` trace and strict P0/P1 analyzers
   remain **unchanged**, including the ±50 RPM significant reversal policy.

**Important:** The analog publication is deliberately synchronous with the
same physical motor/PWM virtual-time updates, not a separately clocked host
timer. Adding a second BEMF clock would introduce a sample/phase lag and
invalidate the frozen P0 proof until independently characterized.

## Invariance proof and verification

\`tests/test_native_virtual_time_module_split.py\` reassembles the new
three includes and compares it byte-for-byte to the pre-refactor original
\`am13e_native_motor_plant.inc\` at commit
\`ed29fc304c45465d9144343ef8a9264ddad8b067\`.

This contract is intentionally stronger than just "the function names
match": it proves that the original solver, MOSFET ideal diode, PWM event
callback, analog code conversion, 1µs tick, and source event order were not
edited while separating modules. Dedicated CI fetches the frozen original
commit. Full P0 Strict and P1 scripted jobs still compile source QEMU and
provide actual SIM_ONLY qualification; an expected P1 reversal failure is
NOT a successful acceptance.

The pre-existing customer gate, original ELF/FC command, and native model
assumptions are unchanged. No physical ESC, calibrated analog frontend,
real MOSFET switching, 12S, or propeller qualification is claimed.

## Explicit next diagnostic boundary

Archived actual QEMU source traces already show the same first Original
Guest PWM pair (Phase 2 high / Phase 1 low, mask \`0x18\`) and −30° initial
rotor phase across smoke/gentle/direct20/steps. A fast direct step
overruns that fixed sector's forward-torque electrical range before its
first observed TIMG12. This refactor **does not** hide or correct that
problem. Future changes to plant physics or guest startup timing require
separate A/B evidence, not an unreviewed part of modularization.

## Generated QEMU build staging (required)

`./build.sh` now stages all three new native `.inc` modules into the
ignored `.build/qemu-src/hw/arm/` worktree before QEMU compilation, in
addition to the original machine and analog/PWM includes. Missing or
symlinked module inputs/outputs fail closed; changed module bytes are
resynchronized. P0 and P1 workflows now watch `build.sh` so build-staging
changes are exercised by actual source-built QEMU tests. No source or
Guest firmware mutation happens inside the virtual motor.
