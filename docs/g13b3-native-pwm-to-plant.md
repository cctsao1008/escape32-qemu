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
