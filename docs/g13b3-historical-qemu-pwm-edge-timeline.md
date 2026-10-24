# E62 G13B3 — Historical QEMU-Clocked MCPWM4 Internal Edge Timeline

## Provenance boundary

This implementation records **executed virtual-clock QEMU MCPWM4 internal
AQ/DB events**, not physical MOSFET switching edges, driver propagation
delay, gate voltage, or verified diode/freewheel paths.

The earlier active-register **one-carrier plan** at 0x5FFE6000 remains
unchanged. That plan can describe the present active register image
without any virtual time having elapsed. By contrast, the new ring at
**0x5FFE7000** stores a record only from an actual QEMU edge timer
callback, the original ZERO callback, a committed PWM register write,
a latched Trip, clock control, or GPIO1 PB13/PINCM45 write.

The new QEMU edge observation timer is completely separate from the
firmware-facing MCPWM ZERO timer. It calls the original output
level evaluator; does not write Guest SRAM, DMA, MMIO registers or
manufacture CAP1, TIMG12, PWM IRQ, BEMF, gate states or plant motion.

Events are causal and timestamped by QEMU_CLOCK_VIRTUAL. QEMU's
simplified AQ/RED/FED model is not silicon timing accuracy, and
the physical high/low power-stage switching waveform remains OPEN.

## Bounded read-only observer

- MMIO base: 0x5FFE7000; size: 0x2000; ESC-SIM only
- Magic: 0x48323645 (E62H); ABI: 1
- Capacity: 128 events; eight 32-bit words per event
- Event ring overwrites old events after capacity; total, dropped,
  invalid counts remain explicit and reset with PWM reset
- Records are read oldest-retained-first; no dequeue/ack/write feature
- Each event: virtual timestamp ns (low/high), event kind,
  six-bit prior level, six-bit next level, native PWM counter,
  ZERO count, PB13/Trip/model validity flags
- Header: running/valid/truncated/callback-source flags; count,
  total and dropped (64-bit); current level/counter/ZERO count;
  model PWM Hz; most recent virtual ns; invalid event count

Event kinds 1..8:

1. QEMU_CLOCKED_AQ_DB_EDGE — QEMU edge-timer callback actually executed
2. QEMU_ORIGINAL_PWM_ZERO_CALLBACK — original PWM ZERO callback
3. QEMU_SHADOW_ACTIVE_LOAD — original active load boundary
4. QEMU_CLOCK_START_STOP — modeled clock enable/disable
5. QEMU_PWM_ACTIVE_MMIO_WRITE — observed register output change
6. QEMU_TRIP_STATE — QEMU modeled Trip latch/clear transition
7. QEMU_RAW_PB13_GPIO_PINCM_BOUNDARY — raw PB13 GPIO/route state
8. QEMU_UNSUPPORTED_AQ_DB_OR_CLOCK_GAP — model evidence invalid

All six output mask bits retain U-H/U-L/V-H/V-L/W-H/W-L order.
Raw PB13 is NOT physical driver enable; output polarity and
driver/board behavior remain independently unqualified.

The host decoder in tools/native_pwm_history.py validates causal
mask continuity, event timestamp order, original ZERO counter,
bounded ring metadata and double-reads all header fields to reject
a changing snapshot. If dropped>0, COMPLETE HISTORY is false even
if the retained tail is internally consistent.

All traces retain:
- historical_physical_mosfet_edges_qualified=false
- gate_driver_deadtime_measured=false
- real_power_stage_freewheel_measured=false
- external_pin_waveform_measured=false
- current_continuous_plant_input_qualified=false
- strict_native_rotor_gate_qualified_by_this_trace=false

## Exact-source build and QTest unit fixture

The new machine/am13e_pwm_history.inc is synchronized by build.sh
into the ignored pinned QEMU 6.2.0 worktree, then rebuilt.

    cd ~/github/escape32-qemu
    git pull --ff-only

    python3 tests/test_native_pwm_history.py
    ./build.sh

    python3 tests/g13b3_pwm_history.py \
      --qemu "$PWD/.build/qemu-src/build/qemu-system-arm" \
      --elf "$PWD/.build/e62-fw-fast-ramp/AM13E-rev17.3.elf"

The test authors a synthetic 100-tick PWM peripheral state through
QTest only; this is NOT actual original Guest PWM control. Assertions
cover clocked 250/400/600ns edge callbacks, 1000ns ZERO event,
shadow load after a real ZERO, raw PB13 observation, TBCLKSYNC
stop, read-only MMIO, bounded ring truncation and strict mode
isolation.

Read-only observer does not change existing PA26 waveform at
0x5FFE4000, source-current/Trip fixture at 0x5FFE5000, or the
model-derived carrier plan at 0x5FFE6000. The new region at
0x5FFE7000 is checked for disjoint address mapping.

## Acceptance remains separate

Native SIX-sector and TWELVE-sector/90ms Strict Rotor Gate tests
remain unchanged and independent. QTest device fixture PASS does
not mean original ESCape32 native rotor stability PASS.

NEXT: host-side bounded drain of the executed event ring at Guest
WFI checkpoints with explicit lost-event qualification, then a
frozen switching waveform test using the separate ideal-diode
CurrentContinuousBLDC. Do not reinterpret an internal QEMU
output mask as a physical gate-driver waveform or alter strict gates.
