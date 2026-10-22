# G13B3A — Original firmware PWM image qualification before VirtualBLDC coupling

## Verified predecessor

Latest passing full CI prior to G13B3A:
[39728279382](https://github.com/cctsao1008/escape32-qemu/actions/runs/39728279382).
The separately opt-in `SIM_ONLY` original-ELF build (with explicitly hypothetical electrical values)
has demonstrated original Firmware DShot CRC/throttle, original ECAP/SysTick timebase calibration,
native MCPWM4 IRQ28/ET1 ZERO, two carrier ZERO events, original `am13e_power_stage_enable()`
returning success, physically connected PB13 and six PWM pads, and actual running TBCLKSYNC.
After that original Gate ON, external physical PA22 nFAULT also latches OST2 and forces
all six PWM outputs low while Cortex-M33 is halted, followed by original native shutdown.
These results prove **authorization and fault shutdown**, not a motor waveform or closed-loop.

## Distinct new evidence

`tools/native_pwm_qualification.py` reads the model's **actual original firmware-owned**
six AQ/DB channel output observer, not `throt`, target duty or test-authored MCPWM registers.
The read-only function checks the *instantaneous* state at the first native Gate return:

- PB13 powered GPIO output, explicitly assumed SIM_ONLY active-high Gate, GPIO pinmux
  and all six physical MCPWM pinmux routes;
- powered MCPWM4 and TBCLKSYNC;
- real hardware OST2/OST3 trip flags clear;
- valid six-output AQ/DB observer status, entire mask `0x3F`, nonzero carrier period,
  six HIGH ticks within `[0, period]`;
- nonzero **differential** phase-voltage command (at least one
  A/B pair has different measured high ticks).

An all-zero valid carrier is *not* accepted as motor energization.
An IRQ or PB13 Gate signal by itself is *not* a six-channel output proof.
Any Trip being latched makes the stage unqualified regardless of the observed duty.
No guest register or SRAM writes are performed by this qualification.

**G13B3A native positive proof**:
[CI run 39756133980](https://github.com/cctsao1008/escape32-qemu/actions/runs/39756133980)
captured the actual guest-owned six-channel output at original Gate return:

```text
G13B3A_NATIVE_OUTPUT_READ_ONLY
  gate_and_pads=true pwm_powered=true pwm_tbclk_enabled=true
  physical_ost2=false physical_ost3=false
  pwm_status=15 valid_mask=63 period_ticks=6251
  six_high_ticks=[0,0,0,6220,0,0]
  six_duties=[0,0,0,0.9950407934730443,0,0]
  acceptable_for_plant=true
```

This is the original firmware's instantaneous six-AQ/DB carrier image,
not a host-injected PWM register profile. The CI result is a **single
nonzero phase voltage command**, not proof that the commutation sequence
continues across six electrical sectors.

The native G13B2E probe prints an explicit
`G13B3A_NATIVE_OUTPUT_READ_ONLY` snapshot under `--probe-native-pwm`; its
`g13b3a_native_pwm` JSON field preserves valid mask, six measured HIGH ticks,
normalized duties (only if valid), physical qualifiers and reason if not ready.
`--require-native-pwm` is a separate opt-in positive gate and is deliberately
**not** enabled in CI until a genuine nonzero firmware-owned output has been observed.

### Run

Use the **SIM_ONLY ideal-BEMF ELF**, not the unqualified Reference ELF:

```bash
cd ~/github/escape32-qemu
python3 tests/test_g13b3_native_pwm.py
python3 tests/g13b2_native_drive_probe.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf /path/to/SIM_ONLY_IDEAL_BEMF/AM13E-rev17.3.elf \
  --throttle 1000 --startup-steps 32768 \
  --slice-ms 300 --runtime-slices 20 \
  --wait-native-bemf-calibration --calibration-wfi-visits 24 \
  --require-drive --probe-native-pwm
```

## G13B3B pending: causal native closed loop

A measured single output image is a prerequisite, not proof of motor control.
The next isolated test must connect original six outputs to VirtualBLDC with
explicit virtual motor and analog front-end parameters, feed the *calculated*
BEMF voltage into the existing simulator-only per-phase CMPSS0 stimulus MMIO,
and let native ECAP1 timestamp a real comparator edge. The host must neither
set firmware commutation state/throttle/IRQ flags nor write native MCPWM AQ/Compare.
Successful native sensorless closed-loop needs **multiple** time-correlated
observations of native output changes attributable to captured BEMF and
native ISR processing, plus negative nFAULT/OC response while coupled.

QEMU `-icount` is a functional virtual-time configuration, not a
cycle-accurate 200MHz AM13E MCU performance specification.
SIM_ONLY board threshold, PWM polarity and virtual motor values are
fictional test assumptions, not validated E62 hardware properties.

## G13B3B — one original PWM carrier seeds VirtualBLDC (read-only)

`tools/native_bldc_seed.py` consumes the qualified original six
PWM duties from the **real native Gate-return snapshot** and
advances the existing G13A `VirtualBLDC` by **exactly one**
native carrier period. The timebase is explicit: 100 MHz MCPWM
and 6,251 observed ticks yield 62,510 virtual nanoseconds.
No time, PWM, Gate, guest SRAM or BEMF registers are written
to QEMU by this seed calculation.

The *synthetic only* motor is specified as:

| Parameter | Test value (NOT E62 measured) |
|---|---:|
| Vbus | 24 V |
| Phase R | 0.3 ohm |
| Phase L | 2 mH |
| Ke, Kt | 0.02 SI-units each |
| Inertia J | 1e-6 kg m2 |
| Viscous friction | 0.0001 N m s/rad |
| Pole pairs | 7 |
| Load torque | 0 |
| Analog Vref and bias | 3.3 V, 1.65 V |
| Analog frontend gain | 0.02 V per phase-BEMF V |

The `--require-native-pwm --require-native-plant-seed` CI
gate requires that the native six-output PWM is physically
qualified, then produces nonzero *virtual* phase currents and
motion over one carrier. **This gate has PASSED** in
[full Firmware-backed CI #39756971492](https://github.com/cctsao1008/escape32-qemu/actions/runs/39756971492),
using guest PWM high ticks `[0,0,0,6220,0,0]` and an observed
6,251-tick carrier at 100MHz:

```text
G13B3B_ORIGINAL_PWM_ONE_PERIOD_PLANT_SEED
  pwm_period_ns=62510
  six_duties=[0,0,0,0.9950407934730443,0,0]
  virtual_mechanical_rpm=3.858541213545304
  virtual_torque_nm=0.006464673356297341
  virtual_phase_currents_a=[0.1244,-0.2488,0.1244]
  virtual_bemf_v=[0.000010,-0.048995,0.048985]
  frontend_words=[67584,67582,67585] # 0x10000 valid + 12-bit ADC code
PASS_G13B3B_GUEST_PWM_TO_ONE_PERIOD VIRTUAL_BLDC_NO_FEEDBACK_INJECTION
```

These are solely the response of the explicitly fictional
`SIM_ONLY` motor model, **not** measured motor values. The three
computed BEMF words are **not** written to CMPSS0/ECAP1 at this stage.

One time step is not an operating motor: no rotor speed
stability, BEMF zero-cross capture, six-step sector progression
or guest consumption of that feedback is demonstrated.
**G13B3C** must explicitly prove repeated causally coupled
native PWM → plant → comparator ECAP → native commutation events.

## G13B3C preflight — Native BEMF capture eligibility (read-only)

The next isolated prerequisite is **not to create an ECAP1 edge**.
First ensure the actual original guest has selected/armed an
appropriate comparator/capture path. The current code supplies
`tools/native_bemf_qualification.py`, whose inputs include the
read-only original ELF `selected_code` and `armed` globals.

Per pinned `motor_bemf.c::compctl(x)` the logical `(x&3)=1..3`
maps to CMPSS0 HPMUX 0..2. `x&4` selects an ECAP rising edge
and otherwise a falling edge. The eligibility check requires:

- Original guest `armed=1` and valid selected phase;
- The actual CMPHPMXSEL matching the native selected phase;
- Powered CMPSS0/ECAP1, active nonzero DAC reference and enabled
  high-comparator majority-filter output;
- ECAP1 Input45, CAPLDEN, running native TSCTR, CEVT1 interrupt
  and correct guest-selected event polarity.

The `--probe-native-bemf` flag reports actual register values at
the first native Gate return. If the original firmware has **not**
armed its BEMF capture yet, the output must remain *Not Ready*;
host BEMF injection or a synthetic ECAP event would be invalid.
This is a read-only diagnostic, not a new positive capture PASS.

Actual closed-loop G13B3C will be accepted only upon repeated
native ECAP CEVT1 IRQs caused by *computed motor* BEMF samples,
and subsequent original firmware commutation/duty changes.
Do not force capture flags, stage firmware variables, or write
the MCPWM AQ output registers from the host.

## G13B3C — Original native BEMF capture-arm observability (qualified)

[Full Firmware-backed CI #39759757725](https://github.com/cctsao1008/escape32-qemu/actions/runs/39759757725)
verified the first **read-only** original Firmware BEMF capture-arm diagnostic.
The earlier `missing=armed` was a local-symbol ambiguity: two distinct
4-byte objects named `armed` were present in the pinned ELF:

- `motor_bemf.c:63`: `0x200005A8` (original BEMF capture state);
- `input_watchdog.c:29`: `0x200015BC` (unrelated watchdog state).

The source-scoped `arm-none-eabi-nm -a -S -l` audit uniquely selects
the first symbol or fails closed. CI read the **actual native guest armed=1**,
`selected_code=5` (phase U, rising), CMPSS0 high mux=0,
DACH=2048, high comparator/filter enabled, ECAP1 Input45, CAPLDEN,
running TSCTR and matching enabled CEVT1 interrupt/polarity.

`--require-native-bemf-arm` enforces positive original-guest BEMF arm
**and** qualified original six-PWM, PB13 physical Gate, no latched
Trip and powered/native comparator/capture routes at the same GDB-halted
breakpoint. Missing/ambiguous native state is a hard failure of this
opt-in gate. No host code writes guest SRAM, IRQ flags, PWM or CAP1.

**Scope:** Arm/route *eligibility* is qualified; physical BEMF
injection, actual ECAP zero-cross events and sustained feedback-dependent
original Firmware commutation are still OPEN, not a closed-loop PASS.
The SIM_ONLY electrical profile remains a fictional test fixture.


## G13B3D — Native PWM/Plant sampled timeline (read-only, no BEMF)

The next two implementation tasks are *native runtime time coupling* and
*continuous native six-output PWM observation*. The G13B3D opt-in gate
uses the original ECAP1 TSCTR at 200MHz (from the original guest-owned
16kHz SysTick/ECAP calibration). Every observation is at a distinct
actual original-main WFI breakpoint reached through real GDB continue.
QEMU virtual time is **never advanced by the host** using clock_step.

At the first legitimate Gate-return and each subsequent native main-WFI
stop, the test reads the original six AQ/DB observed HIGH ticks and
period, PB13/pad/power/Trip qualifiers, BEMF arm/route and ECAP1 TSCTR.
Each bounded positive delta of ECAP ticks is converted to virtual ns;
the Host VirtualBLDC advances only when consecutive sampled six-PWM
images are identical. Changed images are retained as observations but
their intervening interval is marked *unresolved* and NOT integrated
using a fabricated transition time. Even when sampled endpoints
match, the model assumes zero-order hold and does NOT prove no hidden
intermediate transitions.

The command is isolated from previous PASS gates, uses the distinct
SIM_ONLY ideal-reference ELF, and never writes any BEMF stimuli, guest
SRAM, Gate, native MCPWM AQ/DB, ECAP or IRQ flags. Its result is a
**sampled time-coupled plant and repeated native PWM observation**, not
ECAP comparator feedback or native sensorless closed-loop control.

\`\`\`sh
python3 tests/g13b2_native_drive_probe.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf /tmp/e62-fw-sim-ideal-bemf/AM13E-rev17.3.elf \
  --throttle 1000 --startup-steps 32768 \
  --slice-ms 300 --runtime-slices 20 \
  --wait-native-bemf-calibration --calibration-wfi-visits 24 \
  --require-drive --require-native-pwm --require-native-bemf-arm \
  --require-native-timeline --timeline-visits 4
\`\`\`

**Acceptance** requires >=5 chronological native observations and >=2
nonzero integrated host intervals. Each step must preserve valid
original Gate/pads, no OST2/OST3, original comparator/capture-arm
readiness, native 200MHz calibrated timebase, and a bounded
strictly positive original ECAP counter delta. All unknown intervals
and unresolved waveform transitions remain disclosed. Feedback
injection and any claim of native closed-loop commutation stay OPEN.
