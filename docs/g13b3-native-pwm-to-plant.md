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


## G13B3E native BEMF injection (guarded test)

Original Guest Gate/Trip/PWM/ECAP-BEMF capture-arm and calibrated timestamp are verified before every three-phase BEMF injection. The synthetic AnalogFrontend converts actual Host VirtualBLDC currents/velocity/angle into U/V/W samples without clipping. Only simulator-only MMIO 0x5FFE2000/04/08 are written and read back. The original ARM ELF retains control of Gate, six PWM, CMPSS0/ECAP1/IRQ and motor policy. No ECAP capture or native closed-loop status is implied by this gate; G13B3F/H remain OPEN pending actual native evidence.


## G13B3F native zero-cross CAP1 and original IRQ audit

Separate strict opt-in positive gate. A previously injected original host-motor BEMF code must actually cross the guest-owned DAC with the selected native edge polarity. The QEMU CMPSS0 majority filter may then create a genuine ECAP1 CAP1 value. PASS requires a changed read-only CAP1 after that very injection and a strictly increased original firmware motor_bemf.c captured_events SRAM counter, which is only incremented by the original ECAP1_IRQHandler. A disarmed capture after a consumed native event is handled as real original behavior, not overridden. The gate does not imply that the native event was accepted by Rel17 for commutation; G13B3G/H remain OPEN.


## G13B3H fault-under-feedback subset (physical nFAULT)

After five original native timeline voltage samples (including nonneutral VirtualBLDC-derived U/V/W), a separate QEMU run asserts only physical external PA22 nFAULT, while Cortex-M33 is stopped. Hardware OST2 must force all six PWM low asynchronously, and the original Firmware must enter its fault reset/shutdown path when resumed. This is a fault case after model injection, not sustained closed-loop operation or evidence of accepted BEMF commutation. Original fault gate remains unchanged and additionally runs separately.


## G13B3G native Rel17 commutation diagnostic and strict gate

After a physically derived BEMF crossing produces native CAP1 and original captured_events, optionally inspect original motor_event_timer scheduled and serviced data, then continue real original WFI / TIMG12 execution. Only a true original guest one-shot service AND a different still-qualified native six-output PWM image can report the isolated G13B3G PASS. Original firmware may correctly reject an early edge; diagnostic then prints G13B3G_OPEN, never a simulated pass. Separate strict --require-native-commutation exists but is not enabled in CI until real positive evidence. Even a first accepted commutation would not prove sustained closed loop or physical E62 qualification.

G13B3H late native WFI note: after the timeline probe has cleared its
motor-start/Gate/fault-reset debugger breakpoints, the coupled fault test
reinstalls **only** the read-only GDB breakpoint on original
`am13e_app_motor_fault_reset`, before continuing real firmware execution.
No guest SRAM/PC/IRQ/PRIMASK or native safety register is changed.


## G13B3G original Rel17 early-edge negative control

New independent `--require-native-early-rejection` strict gate proves the physically derived phase voltage created a real CAP1/ISR, but the original firmware correctly refused this too-early crossing. It observes original guest `ival`, original ECAP crossing_epoch and calibrated ticks, rejected_events +1, unchanged TIMG12 scheduled and BEMF armed/phase unchanged. If any original information is unobservable or disagrees, fail closed. The early-edge negative control PASS must never be presented as acceptance, native commutation, or sustained closed loop. Subsequent realistic native later-edge timing remains OPEN.


## G13B3G bounded continued native analog-feedback diagnostic

`--extended-native-feedback-visits 384` keeps the original Cortex-M33 running through actual WFI instructions after Rel17 rejects the first real CAP1. On each observed ECAP timestamp, physical Gate/pads/PWM and BEMF arm remain qualified and the Host VirtualBLDC advances only by the real clock delta. It writes ONLY actual motor-derived three-phase QEMU analog stimulus, and may observe subsequent genuine CMPSS0/ECAP1 CAP1/native ISR counts. Original rejection leaves native capture armed. An **accepted** later BEMF must increase native TIMG12 `scheduled` with no guest reject, and a genuinely serviced TIMG12 and different qualified six PWM must follow to prove the *first* feedback-derived commutation. Saturation, safety loss, no later crossing, or incomplete PWM changes stay OPEN with reasons; the test never writes firmware SRAM, CAP1, IRQ flags, PWM or virtual clock. Even one accepted event is NOT sustained sensorless closed-loop.


## G13B3I no-valid-BEMF original timeout (strict negative gate)

The dedicated native-ELF QEMU run allows original motor Gate/PWM/BEMF arming, then supplies **no valid analog U/V/W** (QEMU BEMF stimulus port stays invalid). Guest SysTick alone must reach the original ECAP1 32.768ms timeout. PASS requires original BEMF armed→0, crossing_epoch_valid→0, ECAP TSCTR deadline, original TIMG12 `cancelled` increment, unchanged original `captured_events` and `rejected_events`, shared Rel17 `ertm=100000000` timeout reset, clear physical Trip, and all three QEMU inputs still invalid. Every WFI/timestamp is genuine original Cortex-M33 execution. Host does not write BEMF samples, guest SRAM, clocks, ADC, PWM, CAP1, IRQ, or fault flags. Board-level qualification is separate.


## G13B3G extended feedback QEMU liveness instrumentation

CI #39796856064 and #39797253832 failed *after* two native post-capture WFI observations: a QTest MMIO `readl` timed out, then the GDB breakpoint cleanup timed out. These are QEMU/test-transport liveness errors, **not** native sensorless-commutation observations. The probe previously spawned QEMU with `stderr=PIPE` while never draining the pipe until process termination; long-running diagnostics could therefore block the emulator itself. G13B3G now sends QEMU stderr to a disk-backed file, exports the complete log with the test artifact, and prints its tail for this diagnostic. Guest SRAM, PWM, IRQ, CAP1, gate and physical Trip behavior are unchanged. The original G13B3G positive qualification remains OPEN until a native accepted TIMG12 event and measured next-sector PWM are proved.


## G13B3G read-only TIMG12 status after accepted plant CAP1

Full CI #39807871887 proved a second natural plant-derived rising CAP1 was accepted at 5.375ms, increased original TIMG12 `scheduled`, but a bounded 97-WFI observation lacked proof of TIMG12 ISR `serviced` plus changed six PWM. New native diagnostics take read-only snapshots of TIMG12 clock, +0x1804 CTRCTL, +0x1808 LOAD, +0x1800 count and IRQ MASK/RAW/MASKED at 0x40188000 relative hardware offsets, both immediately upon original accepted event and at the end of the wait. They separately report original guest serviced counter and qualified six-output PWM, to identify whether the timer did not start/expire, the interrupt was unmasked, or the original ISR actually ran without native commutation. The external host never writes these timer regs.


## G13B3G Original TIMG12 ISR serviced but no six-PWM transition

Full CI #39809528852 already confirms original guest TIMG12 at 100MHz initially has CTRCTL=1, LOAD=428299, counter=422268, IRQ mask=1, then the down-counter stops with original guest `serviced` 0→1 and IRQ raw/masked cleared; nevertheless effective six PWM remains `[0,0,0,6220,0,0]`. The problem is AFTER the real timer ISR, not timer clocking. A new read-only diagnostic compares original guest `runtime_aq_updates`, `runtime_commit_count`, `step`, `sine`, `prep`, `timer_armed` with six real MCPWM4 AQCTL shadow/active, compare shadow/active, GLCTL/GLSTS, force flags, before and after original ISR and its following carrier zeroes. No firmware logic, hardware register, or motor parameter is modified to manufacture an accepted step.


## G13B3G original HAL six-output image ownership diagnostics

Full CI #39811079471 proved original Rel17 TIMG12 serviced=1, step 1→2, original selected_code 5→3, runtime_aq_updates 2→3, but measured original MCPWM4 AQ active/shadow both retained `[1,1,1,512,1,1]` and GLSTS latch became 1. The original guest's internally owned `runtime_aq_last[6]`, `logical_aq[6]`, and `logical_compare[6]` are now read via GDB RSP **only** at accepted event and after serviced TIMG12. All values are original ELF SRAM, with no test writes; if a source-local symbol is absent from the pinned ELF, report UNOBSERVABLE rather than inventing an AQ vector. This disambiguates a real nextstep output image from a QEMU shadow/publication emulator error. No status claim of native six-output commutation is made yet.


## G13B3J original deadband/source-clamp diagnosis

Full CI #39812286626 proved original guest sixstep AQ changed from `[0,0,0,2,18,0]` to `[18,0,0,2,0,0]`, with logical compare 3→9, but physical AQ remains `[1,1,1,512,1,1]`. Native backend intentionally clamps high-side PWM for compare <= DBRED−DBFED when the pulse would be shorter than deadtime. Read-only snapshots now include actual native DBCTL, DBRED and DBFED and an auditable per-source clamp classification; absent ELF locals remain unobservable, never fabricated. An additional SIM_ONLY DShot1500 test evaluates the Firmware's authentic ramp versus baseline DShot1000 without touching guest SRAM, ADC, IRQ, PWM, Trip or safety checks. A logical step or low-side-only output is not proof of energized motor closed loop.


## G13B3K conservative two-terminal motor-power-path gate

The original G13A reduced-order star-neutral model accepts a low-side-only waveform as a nonzero phase voltage; this can yield nonzero simulated angular speed/BEMF despite **no** physical high-side source. Full CI #39812286626 measured `[0,0,0,6220,0,0]`: only one low-side output had a positive duty count. That does not qualify an electrically energized BLDC bridge. New strict **G13B3G closed-loop acceptance only** requires measured upper-side PWM and measured lower-side conduction on a distinct phase, as well as original Gate/Trip safety; it is necessary but not sufficient for a realistic motor. The pre-existing G13A SIM_ONLY model regression remains unchanged, while any future claim of accepted native real commutation cannot use its single-leg plant artifact. No PWM, IRQ, DShot, ADC, DAC or firmware variable is written by this gate.


## Correction: native DBRED/DBFED register offsets

G13B3J CI #39817058959 failed because the newly added **diagnostic** reversed the native MCPWM4 register offset mapping. The modeled register readback was DBFED at +0xD0 = 1, DBRED at +0xD4 = 32, DBCTL at +0xC0 = 0x0F0022. This is **not** a Firmware fault or a Trip. The observer now reads those locations with a unit-tested helper, yielding original non-PWM_ENABLE minimum source compare 32−1=31 ticks when the FED path is enabled. Recorded original logical compare 3 and 9 therefore remain below that threshold and the intentional source pulse suppression is expected. No electrical timing, gate, fault, firmware or PWM write was changed.


## G13B3L physically powered plant and untouched Rel17 ramp configuration

G13A Host VirtualBLDC historically accelerates with only a B low-side driven, because of an idealized neutral-voltage mapping. Never use that speed/BEMF as evidence of an energized ESC. G13B3L introduces a separate open-star coasting plant with **zero acceleration** until measured opposite-phase upper/lower duties form a DC-bus path. It never bootstraps motor RPM when only one sink is high. For motor controls, a separate SIM_ONLY configuration includes exactly the prior opt-in board Gate/Dead Time/Trip/BEMF parameters and changes **only** the stock Rel17 `DUTY_RATE=100` (valid 1..100) rather than the baseline `DUTY_RATE=30`. Both original ELF images are independently compiled and compared, preserving baseline regression. This is a simulation tuning hypothesis, not an E62 hardware motor/prop spec. Native effective power and repeated original ECAP/TIMG12 commutation still require separate full firmware-backed strict evidence.


## G13B3L new independent 6-sector original firmware closed-loop runtime

A standalone native WFI-loop runner now drives the separate DUTY_RATE=100 SIM_ONLY original ELF, not the baseline firmware image. At each original-guest WFI, it reads actual MCPWM4 six-output PWM, Gate/pads/Trip, ECAP1 clock/CAP1 and guest captured, rejected, scheduled, serviced, step and selected_code. Only measured opposite-phase high/low PWM enables the separate floating-star motor to accelerate; otherwise it remains at rest or coasts. Computed three-phase BEMF is injected **only** into QEMU-only analog MMIO; it never forces an IRQ or original firmware event. A causal sector counts ONLY following original accepted CAP1, actual TIMG12 service, real original nextstep, and a distinct, measured powered bridge pair. At least six such transitions are required; no one-event success. The Full CI step is initially diagnostic and prints explicit OPEN if there is no complete physical power path or full six-step cycle; strict --require-native-sustained-loop is an opt-in failure gate. This is still synthetic motor and SIM_ONLY electrical hardware; physical E62 ESC qualification remains a separate responsibility.
