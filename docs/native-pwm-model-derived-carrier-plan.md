# E62 G13B3 — QEMU Native MCPWM4 Carrier Switching Plan (READ-ONLY)

## Exactly what was added

The original QEMU AM13E ESC-SIM MCPWM4 computes internal output
levels from its **ACTIVE** Guest-authored AQ / Compare / Independent
RED/FED configuration using am13e_pwm4_level().

Previously the only non-silicon observer at 0x5ffe1000 returned six
HIGH-tick counts and the level at the CURRENT counter. It did not
provide the event boundaries that produced those counts.

This stage adds a **separate read-only simulator-only observer** at
0x5ffe6000. It evaluates the existing active AQ+DB level function at
each counter tick of ONE carrier, compresses equal levels into a
6-bit state sequence and records each modeled transition tick. A
possible counter-wrap transition is explicitly represented as the
carrier tick count (period+1 of the register).

This is NOT a QEMU chronological edge callback recorder. QEMU
currently schedules MCPWM4 ZERO events, not each AQ/DB pin edge.
Therefore no previous or future PWM carrier is reconstructed when
the original Guest may have updated the active image midcarrier.

**Provenance: QEMU_ACTIVE_AQ_DB_ONE_CARRIER_MODEL_RECONSTRUCTION.**

Neither original Guest ESCape32 Rel17.3, QEMU motor feedback/CMPSS/
ECAP, PWM ZERO IRQ, trip hardware logic, gate/PINCM qualifications
nor the 12-sector/90ms extended Strict Gate is modified.

## Source-derived and unproven

- Source-derived: current ACTIVE AQ/Compare/FED/RED output level for
  all six modeled phases, at each integer carrier counter tick.
- Independently verified: integrating the event dwell periods
  exactly reproduces the previous six-output HIGH-tick observer.
- Qualified as MOSFET switching edges: **NO**.
- Historical time-ordered edge callbacks observed: **NO**.
- External gate-driver propagation/deadtime measured: **NO**.
- Unobserved ACTIVE register changes during an earlier carrier
  accounted for: **NO**.
- Deadtime model: previously supported AQ/DB RED/FED arithmetic,
  not measured TI silicon or a real power stage.
- Freewheel / diode conditions verified by native hardware: **NO**.
- Direct CurrentContinuousBLDC input readiness: **NO**.

The new observer explicitly refuses unsupported AQ/deadband, inactive
clock, overflowed transition lists and unknown read offsets. Writes
are always rejected; it cannot program Guest PWM or create IRQs.

## Read-only ABI, ESC-SIM, QTest only

Mapped at 0x5ffe6000, 32-bit aligned. The address was moved from the original prototype's 0x5ffe4000, which is already reserved for the PA26 Waveform Fixture; compile-time non-overlap checks now protect all existing ESC-SIM fixture windows:

    +00 0x50323645  "E62P" signature
    +04 status [0] running, [1] fully valid, [2] overflow,
               [3] MODEL_DERIVED
    +08 total carrier ticks (period register + 1)
    +0c event count (max 64; overrun rejects)
    +10 initial six-bit level mask at tick 0
    +14 last six-bit mask at tick period
    +18 modeled carrier timer clock Hz
    +1c modeled current counter value
    +20 original timer ZERO event count
    +24 low32 of QEMU virtual nanoseconds
    +28 high32 of QEMU virtual nanoseconds
    +2c ABI version = 1
    +40+8i modeled transition carrier tick, 1..carrier ticks
    +44+8i six-bit mask AFTER modeled transition

Masks order: bit0 U-H, bit1 U-L, bit2 V-H, bit3 V-L,
bit4 W-H, bit5 W-L (matches original six-output observer).
A wrap transition at tick=total_carrier_ticks returns to the
tick0 mask. No event timestamp is claimed to be an observed
chronological physical edge.

QEMU recomputes the model-derived plan only from actual original
ACTIVE PWM registers. The host read protocol checks the initial and
final headers match to reject concurrently changing snapshots,
validates monotonic transitions and nonoverlap, and independently
reconstructs all six HIGH-tick counts from event dwell duration.

`capture_qemu_carrier_plan()` returns an immutable object whose
`to_dict()` always marks these **false**:

    historical_chronological_edge_callbacks_observed
    midcarrier_register_changes_observed
    physical_gate_driver_deadtime_qualified
    external_mosfet_output_edges_measured
    physical_freewheel_topology_qualified
    current_continuous_plant_input_qualified
    native_closed_loop_motor_qualified

Even if the external gate/pad observer is qualified independently,
the carrier plan by itself is NOT enough for a physically
time-resolved CurrentContinuousBLDC drive.

## Host unit tests and real QEMU QTest preflight

After pulling a new machine source revision, the original worktree
QEMU must be rebuilt. The QEMU binary is not bundled or modified in
place by Python:

    cd ~/github/escape32-qemu
    git pull --ff-only
    python3 tests/test_native_pwm_switching_plan.py

    ./build.sh

    python3 tests/g13b3_pwm_switch_plan.py \
      --qemu "$PWD/.build/qemu-src/build/qemu-system-arm" \
      --elf "$PWD/.build/e62-fw-fast-ramp/AM13E-rev17.3.elf"

The QTest device fixture programs a synthetic 100-tick carrier
using QTest-only writes, independently of original Guest execution.
It asserts the exact AQ transition masks for U/V/W upper outputs;
tests RED/FED on an independently authored complementary pair;
verifies an unlatched shadow image does not change the modeled
active carrier; proves unsupported DB mode fails closed and
Strict (esc-sim=off) hides this non-silicon observer.

The CI tests run before independent L/M native acceptance. An
early preflight cannot imply the motor's extended rotor-direction
gate has passed. It is a **QEMU model** test only.

## Next requirements BEFORE Native closed-loop current-continuous plant

1. Time-ordered chronological output edge events from the native
   QEMU PWM execution, not merely the present-register carrier plan.
2. Bounded timestamped capture across native Guest ZERO/shadow
   loads, midcarrier updates and Trip/Gate changes.
3. External high/low power-stage switching/diode assumptions that
   are explicitly distinct from MCU internal modeled output.
4. Frozen input waveform comparison and energy passivity check,
   with the original Strict Rotor Gate unchanged.

Do NOT silently treat this carrier plan as an actual historical
edge trace or use it to emit BEMF feedback. The current scope
deliberately ends at independent source-derived level validation.
