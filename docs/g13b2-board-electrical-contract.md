# G13B2 — Board electrical profile required for native motor enable

## Hardware profile is missing in the pinned CI ELF

The `ESCape32` repository commit
`b0204670515d2de0b2480b52273038f1ee13d30a` builds the
unmodified Rel17.3 core with the AM13E Reference board option.
`mcu/AM13E/config.cmake` defaults
`AM13E_BOARD_BOARD_PROFILE_FILE=""`.
`mcu/AM13E/hal/motor_output_configuration.h` therefore defines
`AM13E_MOTOR_OUTPUT_CONFIGURED=0` and fails closed.

This is **not** a simulator deadlock, a missing DShot frame or a
request to bypass a safety feature. No real E62 gate-driver
truth table, isolation, overcurrent sensing or PWM power-stage
wiring has been supplied and validated within this model.

## Exact compile-time board contract (no guessed physical values)

| Required symbol/condition | Meaning |
|---|---|
| `AM13E_MOTOR_GATE_ACTIVE_LEVEL` | PB13 gate ON level, 0/1 |
| `AM13E_MOTOR_PAD_INVERT_MASK` | Six pad polarities, 0..63 |
| `AM13E_MOTOR_OUTPUT_RED_TICKS` | Rise delay at 100 MHz TBCLK |
| `AM13E_MOTOR_OUTPUT_FED_TICKS` | Fall delay, 0 for independent gate topology |
| `AM13E_MOTOR_MIN_DEAD_TICKS` | Board's guaranteed minimum nonoverlap |
| `AM13E_MOTOR_NFAULT_ACTIVE_LOW` | Physical nFAULT polarity |
| `AM13E_MOTOR_GATE_RESET_INACTIVE=1` | External reset-off wiring is proven |
| `AM13E_OC_U_DAC_CODE` / `V` / `W` | Three measured overcurrent-trip DAC thresholds, 1..4095 |
| `AM13E_OC_U_INVERT` / `V` / `W` | Three analog overcurrent comparator output polarities |

For a `PWM_ENABLE` topology, the original `PWM_ENABLE` selector,
`AM13E_MOTOR_PWM_ENABLE_TOPOLOGY=1`, and
`AM13E_MOTOR_PWM_ENABLE_DRIVER_DEAD_NS` are additionally required.
That topology has a different A/B driver meaning and must **not**
be inferred from independent complementary gate assumptions.

The nFAULT route is PA22 → INPUTXBAR2 → PWM TRIP2 OST2.
The independent overcurrent route uses CMPSS1/2/3 high
comparators → PWMXBAR TRIP3 OST3. All software readbacks and
asynchronous trip overrides must be preserved, not stubbed or
pre-set to 'ready'. A real virtual electrical board fixture
must define its own model of these inputs and demonstrate faults
actually latch off the outputs before positive gate arming is tested.

## Required next evidence

Even after a reviewed **simulator-only virtual board** is provided
(clearly distinguished from Quanta/E62 production hardware),
positive native closed-loop is accepted only when actual original
ESCape32 source compiled with that explicit board contract:

1. Receives a physically timed, CRC-valid command through
   PA26/TIMG4/DMA without direct SRAM/`throt` modification.
2. Completes its own neutral arming duration and input watchdog
   logic, while preserving gate-off state on invalid input or nFAULT.
3. Configures all six output pads, MCPWM Trip/OST/OC protection
   and Gate Enable from native firmware execution.
4. Drives the QEMU-observed six PWM outputs into a declared
   Virtual BLDC/analog frontend without any externally authored
   PWM-register image.
5. Receives BEMF via CMPSS0→ECAP1 and updates the native
   commutation/duty sequence causally from capture events.
6. Proves a negative trip test makes physical output impossible
   and requires a legitimate rearm sequence.

Do not claim sensorless closed loop from the current G13A QTest
peripheral wiring and G13B0 reference fail-closed validations.

All values in a virtual-board fixture are **simulation assumptions**
unless independently backed by electrical schematic, gate-driver
datasheet, measured thresholds and actual PCB wiring. They must
never be marketed as validated E62 hardware safety data.

## G13B2A — SIM_ONLY compile/build progress

The **SIM_ONLY** profile now lives at
`tests/fixtures/g13b2_sim_only_board.cmake` in the QEMU integration
repository, NOT in ESCape32's production Reference source tree.
It is applied to a second build of the pinned original-ELF source:

```sh
cmake -S /tmp/e62-escape32 -B /tmp/e62-fw-sim-only \
  -G 'Unix Makefiles' \
  -DESCAPE32_BUILD_AM13E=ON \
  -DAM13E_SDK_ROOT=/tmp/e62-sdk \
  -DG13B2_SIM_ONLY_OPT_IN=ON \
  -DAM13E_BOARD_BOARD_PROFILE_FILE="$PWD/tests/fixtures/g13b2_sim_only_board.cmake" \
  -DAM13E_BOOT_LINKER_SCRIPT=/tmp/e62-escape32/boot/mcu/AM13E/config.ld
cmake --build /tmp/e62-fw-sim-only --target AM13E-rev17.3.elf -j 2
```

Profile values are **purely fabricated simulator assumptions**,
not proposed E62 electrical configuration: active-high PB13;
un-inverted independent MCPWM A/B; RED=32 ticks at virtual 100MHz
(320ns); FED=0; minimum gap 32 ticks; active-low PA22 nFAULT;
simulated hardware-reset gate inactive; CMPSS1/2/3 DACH=2048
with non-inverted OC outputs. The original runtime safety
preconditions, `motor_output_configuration.h` static assertions
and native nFAULT/OC Trip readiness logic are unchanged.

Explicit CMake opt-in is required; the CI negative configuration
test must fail without `-DG13B2_SIM_ONLY_OPT_IN=ON`.
The CI compares SHA/bytes of the baseline Reference ELF and the
separately produced `SIM_ONLY` ELF to ensure the profile was
actually compiled.

[CI #39641209305](https://github.com/cctsao1008/escape32-qemu/actions/runs/39641209305)
passed the opt-in rejection, independent SIM_ONLY native build,
and unchanged Reference G0–G13 regressions.

The new `tests/g13b2_sim_only_preflight.py` is a distinct
**negative** native-ELF simulator check: it traces startup
without any guest input/register spoofing, verifies physical gate
and six outputs remain disconnected before independent Trip
qualification, and records the first real CPU fault/BFAR. A
positive Gate/Trip readiness verdict is **not** implied by this
test or by successful firmware compilation.

## G13B2B — Safety hardware model still required

The current QEMU contains a functional MCPWM4 engine and
CMPSS0/ECAP1 BEMF path. Its independent three-phase OC/Trip
hardware still lacks complete native CMPSS1/2/3, INPUTXBAR,
PWMXBAR and PWM4 OST2/OST3 asynchronous shutdown modeling.
QEMU must model **actual signal propagation and latching**:
an asserted PA22 nFAULT or any comparator overcurrent must
set the corresponding OST even if CPU interrupts are masked;
the PWM output observer must respect the hardware kill, and
Firmware must observe/readback/acknowledge real protection
state. Neither constant 'ready' reads nor host forcing PB13
active is an acceptable workaround.

Native positive arming and virtual motor closed-loop therefore
remain OPEN pending separately demonstrated hardware Trip model,
its negative/positive regression controls, and firmware-owned
real DShot neutral window and commutation updates.

## G13B2C — Native SIM_ONLY neutral protection configuration: PASS

Verified [GitHub Actions #39693884065](https://github.com/cctsao1008/escape32-qemu/actions/runs/39693884065):
the *original ELF* initializes all three CMPSS high comparators
(DACH=2048), PA22→INPUTXBAR2→PWMXBAR TRIP2 and
CMPSS1/2/3→PWMXBAR TRIP3, MCPWM4 TZSEL=0x60000
and TZCTL=0xA. On actual runtime WFI, CPU CFSR/HFSR=0,
no OST flags, PB13 DOE=0x2000, DOUT=0, GPIO-output PINCM=0x81,
six PWM pad PINCM remain GPIO input and TBCLKSYNC remains zero.
The neutral-state test is read-only; test-side QTest supplied only
explicit healthy external 12-bit current analog samples.

## G13B2D — Original-ELF physical fault ISR and shutdown: PASS

Verified [GitHub Actions #39694030611](https://github.com/cctsao1008/escape32-qemu/actions/runs/39694030611).
`tests/g13b2_native_fault.py` separately asserted actual
*external* PA22 nFAULT, W-phase, V-phase, and U-phase analog
overcurrent while Cortex-M33 was halted at genuine native WFI.
No peripheral status, IRQ, firmware SRAM, or gate/pad state was
manually patched or set by the host.

| External physical stimulus | Latched native TZ flags | CPU result |
|---|---|---|
| PA22 asserted nFAULT | OST2 = `0x20000` | MCPWM4 IRQ IPSR 44 → original shutdown |
| CMPSS1 / W current over DACH | OST3 = `0x40000` | MCPWM4 IRQ IPSR 44 → original shutdown |
| CMPSS2 / V current over DACH | OST3 = `0x40000` | MCPWM4 IRQ IPSR 44 → original shutdown |
| CMPSS3 / U current over DACH | OST3 = `0x40000` | MCPWM4 IRQ IPSR 44 → original shutdown |

Each fault latched **with the CPU halted**, produced native
MCPWM4 interrupt flag `0x04`, then on CPU continuation entered
the original firmware `MCPWM4_IRQHandler()` and ultimately the
original `am13e_app_motor_fault_shutdown()`.
These are **negative protection proofs with no drive active**;
they do not yet prove Trip kills an already armed active native
motor. G13B2B's separate QTest virtual output test establishes
immediate PWM suppression for artificially configured QTest PWM.

## G13B2E — Positive native DShot-to-gate probe: OPEN until demonstrated

`tests/g13b2_native_drive_probe.py` is an experimental bounded
original-ELF probe. It uses a genuine PA26 DShot600 waveform via
TIMG4/real DMA to update the guest-owned throttle, waits for the
original `am13e_motor_output_start()` and
`am13e_power_stage_enable()` functions, then independently reads
the actual GPIO PB13 level, six MCPWM pads, PWM TBCLK and OST flags.
Without all of these *observed native guest actions*, the probe
prints `G13B2E_OPEN_NO_POSITIVE_NATIVE_DRIVE_PROOF`, not PASS.
Only `--require-drive` enforces the positive acceptance in a
separate strict run. It must never substitute register or
firmware state writes for a positive validation.

Native closed-loop remains entirely **OPEN** after this stage;
no native motor speed, BEMF zero-cross feedback, phase
commutation causality or real electrical hardware approval
has been established.

### First original positive-input probe: safe native rejection

[GitHub Actions #39694443423](https://github.com/cctsao1008/escape32-qemu/actions/runs/39694443423)
completed successfully as a **diagnostic** (not gate acceptance).
The actual physical PA26 waveform was DMA captured and CRC accepted
by unchanged native Rel17 (frame `0x7D0A`, guest `throt` `0→953`).
The guest genuinely entered `am13e_motor_output_start()`, but
subsequently entered `am13e_app_motor_fault_reset()` without ever
calling `am13e_power_stage_enable()`. At rejection,
PB13 DOUT=0, six physical PWM pads remain GPIO input, TBCLKSYNC=0,
TZFLAGS=0 and CFSR/HFSR=0.

This proves real command-to-start *attempt* and genuine fail-closed
software refusal, **not** positive gate permission. Candidate native
guards in `motor_output_runtime.c` are independent
`am13e_app_motor_nfault_trip_ready()` and
`am13e_app_motor_bemf_reference_start_ready()`.
The strict GDB-return tracing extension will determine which
original function returned false; never replace these calls with a
mock ready bit.

Separately, original `motor_bemf.c` deliberately initializes CMPSS0
DACH to 0, which is **not** a valid calibrated Vdc/2 neutral.
The only documented non-SC5 activation is
`am13e_app_motor_bemf_reference_set()` with a valid explicitly
board-supplied analog reference. SIM_ONLY must keep this distinction
clear: a future *test-only* neutral fixture is not production
calibration evidence.

### G13B2E ADC0 IRQ24 original native fail-closed diagnosis

In [CI #39695429331](https://github.com/cctsao1008/escape32-qemu/actions/runs/39695429331),
opt-in ideal virtual BEMF DACH=2048 changed original
`am13e_app_motor_bemf_reference_start_ready()` **0→1** and
`am13e_motor_output_start()` **0→1**, with original nFAULT
readiness remaining 1. Nevertheless, the native code later reached
`am13e_app_motor_fault_reset()` with IPSR=24 (ADC0_INT1_IRQn=8),
before its own `am13e_power_stage_enable()` was called.
PB13 remained inactive, the six pads remained isolated and
TBCLKSYNC remained 0. This diagnostic overall CI SUCCESS is
**not** a positive motor-output PASS.

Original `mcu/AM13E/hal/analog_runtime.c::adc_complete()` explicitly
checks **both** `DL_ADC_getInterruptStatus()` and
`DL_ADC_getInterruptResultReadyStatus()`; if either is false it
calls `adc_fail_closed()` and the native fault-reset path.
TI pinned SDK `hw_adc.h` defines ADCINTFLG ADCINT1 bit0 `0x1`
and ADCINT1RESULT bit8 `0x100`. The original G4 QEMU ADC model
had generated only bit0 after genuine SOC completion. The QEMU
model was corrected to latch bit8 **only after real ADCRESULTs
are committed**, and to acknowledge the paired status on
the native ADCINT1 W1C. A software-forced ADC IRQ continues
to set only bit0: it cannot fake completed ADC results.

`tests/g4_adc_sequencer.py` independently checks all three ADCs:
true SOC completion asserts `0x101`, W1C releases both status
bits, and a forced IRQ without EOC cannot set bit8. This is
a motor safety fidelity correction, **not** an ADC analog
calibration, power-stage safety qualification, or native Gate
authorization. The full ideal-BEMF original-ELF regression must
establish subsequent progress before any G13B2E positive PASS.
