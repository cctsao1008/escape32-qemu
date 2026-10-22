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
motion over one carrier. The result records three computed
BEMF codes for future feedback, but these are **not**
published to CMPSS0/ECAP1 at this stage.

One time step is not an operating motor: no rotor speed
stability, BEMF zero-cross capture, six-step sector progression
or guest consumption of that feedback is demonstrated.
**G13B3C** must explicitly prove repeated causally coupled
native PWM → plant → comparator ECAP → native commutation events.
