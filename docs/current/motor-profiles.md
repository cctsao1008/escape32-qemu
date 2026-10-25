# G16: minimal named motor profiles for original-Guest E62 SITL

**Boundary:** The original ESCape32 Rel17.3 ELF is unchanged. The Host CLI
selects *motor physics*; original Guest firmware continues to own DShot,
PWM, CMPSS/ECAP, TIMG12 and commutation. Profile selection is **not**
motor/propeller calibration, physical qualification, or proof of stable RPM.

## Named profiles

| Name | Source | 24 V | Poles / pole pairs | R phase (assumed) | L phase (assumed) | Kt model | Rotor J |
|---|---|---|---|---|---|---|---|
| `legacy` | historical synthetic G13B3 | yes | 14 / 7 | 0.3 Ω | 2 mH | 0.02 Nm/A | 1e-6 kg·m² |
| `reciprocal` | historical reciprocal synthetic | yes | 14 / 7 | 0.3 Ω | 2 mH | 0.14 Nm/A | 1e-6 kg·m² |
| `ecx87-kv147` | maxon EC 87 flat UAV p.1, Part 773484 | yes | 42 / 21 | 0.053 Ω | 0.024 mH | 0.0649 Nm/A | 1.3e-4 kg·m² |
| `ecx87-kv210` | maxon EC 87 flat UAV p.1, NEW KV210 | yes | 42 / 21 | 0.0283 Ω | 0.00875 mH | 0.0454 Nm/A | 1.3e-4 kg·m² |

**Simplifications:** Datasheet terminal R/L are phase-to-phase; in this
balanced-star model each is divided by two. Published Kt is provisionally
used as the phase-sine model Kt, with `Ke_electrical = Kt / pole_pairs`
to retain model electrical/mechanical energy reciprocity. That interpretation
is **not a verified Ke waveform mapping** or replacement for measuring phase
BEMF. Viscous friction `0.0001 Nm/(rad/s)`, zero load torque, zero propeller
inertia, 1.65 V analog bias and 0.02 V/V analog gain remain **uncalibrated
SIM_ONLY assumptions**, not maxon specifications.

## CLI use (no virtual UART needed)

Build the ordinary QEMU as in repository README, then provision the
**selected profile's original-firmware Cfg Flash** with exactly one field
changed: `telem_poles=42` (motor poles, **not** pole pairs). Rel17
`telem_poles` affects RPM telemetry; it does **not** program six-step
commutation timing, BEMF zero crossings or motor physics.

```bash
python3 tools/sim_motor_cfg.py --sim-only-opt-in \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --motor-profile ecx87-kv147 \
  --output artifacts/e62-g13b3-ecx87-kv147-cfg-flash.bin
```

Run the existing strict Guest runner, **reusing its existing flags**, but
selecting the corresponding model and pre-boot Cfg image:

```bash
python3 tests/g13b2_native_drive_probe.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --throttle 1500 --startup-steps 32768 \
  --slice-ms 300 --runtime-slices 20 \
  --wait-native-bemf-calibration --calibration-wfi-visits 24 \
  --require-drive --require-native-pwm --require-native-bemf-arm \
  --require-native-sustained-loop \
  --sim-only-cfg-flash artifacts/e62-g13b3-ecx87-kv147-cfg-flash.bin \
  --motor-profile ecx87-kv147 \
  --sustained-wfi-visits 2800 --sustained-sectors 12 \
  --sustained-min-integrated-ns 90000000 \
  --initial-electrical-degrees -30 \
  --sim-only-clocked-current-continuous \
  --sitl-native-pwm-history \
  --sitl-trace-output artifacts/e62-g16-ecx87-wfi-history.json \
  --artifact artifacts/e62-g16-ecx87-native.json
```

Use `ecx87-kv210` instead in **both** commands to change motor type.
Mismatched image/profile combinations fail before starting the Guest.
Original Guest `Cfg` readback must confirm 42 poles at its real WFI.
The old G14 CI continues to use `reciprocal` and its **unchanged**
original Cfg image; the strict 12-sector/90ms rotor gate is not waived.

**Not implemented intentionally:** Guest UART `set/get/save` transport,
editable arbitrary motor JSON, arbitrary CLI firmware parameters, dynamic
propeller aerodynamics, physical analog signal conditioning and production
Flash writes. Add these only when justified by validated use cases.
