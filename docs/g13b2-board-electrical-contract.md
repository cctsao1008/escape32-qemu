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
