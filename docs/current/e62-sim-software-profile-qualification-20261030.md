# E62 #5/#7 — SIM_ONLY Configuration Profile and Qualification Boundary

Date: 2026-10-30. **Software simulation only** is the active project acceptance
scope; physical board signoff is deliberately excluded from issue closure.

## Implemented in QEMU source

- `-M am13e23019,esc-sim-native-motor-profile=ecx87-kv147`
  is the unchanged default native-model parameter set.
- `-M am13e23019,esc-sim-native-motor-profile=ecx87-kv210`
  selects the maxon EC87 KV210 R/L/Kt motor model, with the same
  electromagnetic reciprocity convention as the existing KV147.
- Both use 24V, 1us virtual plant tick, 21 pole pairs, and the
  declared uncalibrated 1.65V/0.02 BEMF frontend. These are simulation
  assumptions, not an E62 product hardware profile.
- The motor QTest read-only region 0x5ffeb000 returns effective values:
  offset 0x8c Kv rpm/V, 0x90 phase resistance in micro-ohm,
  0x94 phase inductance in nH, 0x98 terminal Kt in micro-Nm/A,
  and 0x9c simulated bus in mV. The probe now checks every value
  before advancing the Guest. A profile declaration without a QEMU
  numeric readback is rejected.
- The firmware `telem_poles` remains a **separate original Guest Cfg
  preboot provisioning**; both EC87 motor variants are 21 pole pairs.
  Do not vary startup policy to make a failing model green.

## Versioned config

`configs/e62-sim-profile-matrix-v1.json` defines motor, virtual time,
BEMF frontend, OC sensor approximation, and #5/#7 study gates.
`python3 -m tools.e62_sim_profile_contract --output result.json` validates
its schema/units against the executable model constants, and reports
model-limited phase-quantization and alias risk for each motor and RPM.
**It does not certify a successful second startup, nor any hardware
measurement.** In particular, a 1kHz `BEMF_FRONTEND` diagnostic rate is
not the three ADCs' real conversion/snapshot rate.

## Issue acceptance

- **#5**: for each chosen model and explicitly versioned coast scenario,
  accept second demand only on actual QEMU Guest PWM/CAP1/TIMG12, DShot
  continuity, rotor sign and reversal-free source events. 300ms failure
  remains a failure, not a waiver. Low BEMF and rank aliasing may
  legitimately result in a **fail-closed rejection**, which does not
  establish successful windmill re-acquisition.
- **#7**: require the original source fault tests (nFAULT, loss/WWDT,
  OC-U/V/W → OST3) to retain real Guest fault response and
  **all-six-safe-off/no-autorearm** within virtual machine evidence.
  Currents in the 4095 overrange injection are *source ADC-like
  fixture values*, not actual motor current. Config may vary plant,
  input timing and analog assumptions but must not mutate fault
  acceptance to suppress failures.

The profile schema and narrow source effective-parameter gate can be
PASS independently; **Issue functional closure still requires actual
runtime multi-profile full-scenario evidence**, not unit-test-only PASS.
