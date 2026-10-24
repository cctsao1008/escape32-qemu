# E62 Functional SITL — DShot Scenario Test Plan v1

**Status:** Scenario design only. The current `tests/g13b2_native_drive_probe.py` accepts `--throttle` as a single value; it does not yet execute multi-stage scenarios. JSON in this package is not an existing CLI input.

## Scope

- Keep pinned original ESCape32 Rel17.3 ELF and QEMU integrity policy.
- Stimulate the original DShot600 path through simulated PA26 wire transitions and original DMA/CRC decode; never overwrite guest throttle, memory, IRQ or ECAP registers.
- Generate simplified functional analog BEMF referenced to observed native commutation state and its timing. Let the original comparator/ECAP/TIMG12 path capture and respond.
- Validate firmware input, output, interrupt/commutation and fault-handling behaviour. Do **not** use physical rotor stability or motor accuracy as a functional-SITL PASS requirement.
- Define T0 after genuine DShot-zero neutral arming; the original approximately 250 ms SysTick arming requirement is a prerequisite, not part of the scenario timer.

## Core scenarios

| Case | Stimulus | Test duration |
|---|---|---:|
| T01 — Ramp 0→90 + Hold | 0→90% linear over t=0–1 s, hold 90% from t=1–11 s | 11 s |
| T02 — Step Sweep | 0% t=0–10s, 10% t=10–20s, …, 100% t=100–110s | 110 s |

Notes: 0% is DShot value 0. Positive normalized command % is mapped to DShot data values 48..2047 using the proposed mapping `round(48+1999×pct/100)`; this is not a guarantee of linear ESC output duty or mechanical RPM. DShot packet repetition is nominally 1 kHz as a proposed configuration, to be checked against the original firmware's watchdog and the simulator's performance. Distinguish virtual time from host wall time.

## Pass/fail observation requirements

1. Original DShot decode/CRC accepts input and guest-owned throttle changes at intended virtual-time transitions.
2. For positive-throttle windows, observe native guest PWM outputs, gate/trip conditions, BEMF comparator capture and guest-owned TIMG12 serviced commutations.
3. During 0%, verify valid neutral frame reception; no physical RPM criterion applies.
4. No unexpected HardFault, watchdog, unqualified trip, or guest bypass. Capture exceptions and stimulus timestamps, not just aggregate totals.
5. Produce per-stage JSON evidence: command %, encoded DShot value, intended virtual t, actual received t, guest throttle, six PWM channels, BEMF/CAP1 acceptance count, TIMG12 service count, fault status, PASS/FAIL/OPEN with reason.

## Implementation sequence

1. Add a virtual-time **DShot scenario sequencer** around the existing original-guest wire sender; maintain periodic CRC-valid frames, change values on stage boundaries.
2. Add a lightweight **functional BEMF source**, using real guest commutation state to select analog phase and crossing timing. Preserve the path through comparator → ECAP → original ISR → TIMG12. Do not inject ECAP/IRQ or guest state directly.
3. Create an independent **scenario oracle** for per-stage functional results. Keep the existing strict physical rotor gate as a separate experimental test, not a dependency.
4. First validate a short smoke scenario, then run the exact 11 s and 110 s acceptance profiles. Report guest virtual time, execution speed, and watchdog behaviour.

### Explicit non-goals

No exact MOSFET switching transient model, current-continuous plant, real shaft RPM, torque/efficiency, or claim of hardware-grade closed-loop rotor stability is required for functional ESCape32 smoke/regression validation.
