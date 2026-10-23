# E62 SIM_ONLY Electromagnetic Reciprocity A/B (G13B3M)

## Scope and boundaries

The pinned ESCape32 Rel17.3 Guest firmware, Flash Cfg, QEMU AM13E model,
DShot600/CRC/250ms ARM, native MCPWM/Gate/Trip safeguards, CAP1/TIMG12
and **the independent strict rotor-direction gate** are unchanged.

The A/B changes only the opt-in host virtual motor Kt parameter.
Baseline runs still use original model constants. These synthetic
parameters are NOT Quanta E62 motor-winding or electrical specifications.
Current commutation resets the branch-current vector and the
sampled-hold model uses Euler integration; numerical energy balance,
commutation transient fidelity, and real rotor stability remain OPEN.

## Electromagnetic identity, not full energy conservation

The unchanged VirtualBLDC.sample() uses:

    e_i = Ke_electrical * pole_pairs * omega_mech * sin(theta_i)
    Te = Kt_mechanical * sum_i(i_i * sin(theta_i))

At the same instant:

    sum_i(e_i * i_i) = Te * omega_mech
    Kt_mechanical = Ke_electrical * pole_pairs

Pinned baseline Ke_electrical=0.02, p=7, Kt=0.02:
theoretical instantaneous Pe/Pm=7 (non-reciprocal).

Separate opt-in reciprocal Ke_electrical=0.02, p=7, Kt=0.14:
theoretical instantaneous Pe/Pm=1. This identity does NOT prove
physical motor calibration or 90ms rotor stability.

## 1. Audit the retained local GCC15 baseline, no firmware rerun

    cd ~/github/escape32-qemu
    git pull --ff-only
    python3 tests/test_native_motor_reciprocity.py

    python3 tools/native_energy_reciprocity_audit.py \
      --trace artifacts/g13b3m-wfi-fixed-trace.json \
      --profile legacy --allow-pre-profile-legacy-trace \
      --output artifacts/g13b3m-legacy-em-audit.json

The old trace lacks embedded motor-model provenance. The explicit
pre-profile flag permits auditing it using pinned source constants,
and labels this as an assumption rather than embedded evidence.

## 2. Separate reciprocal motor-model trial (same GCC15 ELF)

    mkdir -p artifacts
    set -o pipefail
    python3 tests/g13b2_native_drive_probe.py \
      --qemu "$PWD/.build/qemu-src/build/qemu-system-arm" \
      --elf "$PWD/.build/e62-fw-fast-ramp/AM13E-rev17.3.elf" \
      --throttle 1500 --startup-steps 65536 \
      --slice-ms 300 --runtime-slices 20 \
      --wait-native-bemf-calibration --calibration-wfi-visits 24 \
      --require-drive --require-native-pwm \
      --require-native-bemf-arm --require-native-sustained-loop \
      --sim-only-cfg-flash "$PWD/artifacts/g13b3n-original-cfg-flash.bin" \
      --sustained-wfi-visits 2800 --sustained-sectors 12 \
      --sustained-min-integrated-ns 90000000 \
      --initial-electrical-degrees -30 \
      --sim-only-reciprocal-motor \
      --artifact artifacts/g13b3m-reciprocal.json \
      --sitl-trace-output artifacts/g13b3m-reciprocal-trace.json \
      2>&1 | tee artifacts/g13b3m-reciprocal.log
    echo "NATIVE_RECIPROCAL_PROBE_EXIT=${PIPESTATUS[0]}"

A failed native run may leave only a PARTIAL_EXCEPTION trace. This
is not a PASS. The native strict 12-sector criteria are unchanged.

## 3. Audit the new trace and compare

    python3 tools/native_energy_reciprocity_audit.py \
      --trace artifacts/g13b3m-reciprocal-trace.json \
      --profile reciprocal \
      --output artifacts/g13b3m-reciprocal-em-audit.json

    python3 tools/native_motor_ab_compare.py \
      --baseline-trace artifacts/g13b3m-wfi-fixed-trace.json \
      --reciprocal-trace artifacts/g13b3m-reciprocal-trace.json \
      --allow-pre-profile-legacy-baseline \
      --output artifacts/g13b3m-model-ab-comparison.json

The comparator requires identical ELF SHA256, initial rotor pose,
required sectors and integration time, and no Host writes to Guest
registers. It reports observed CAP1/TIMG12, RPM, current and direction
data. The A/B traces can legitimately have different Guest outcomes
because their analog BEMF feedback depends on the motor plant.

## 4. Independent strict acceptance remains the only rotor gate

    python3 tools/native_extended_run_gate.py \
      --artifact artifacts/g13b3m-reciprocal.json \
      --min-sectors 12 --min-integrated-ns 90000000 \
      --min-powered-pwm-samples 600 \
      --output artifacts/g13b3m-reciprocal-strict-verdict.json

A missing artifact or nonzero exit is FAIL/OPEN. Neither the energy
reciprocity audit nor the A/B comparator claims strict-gate PASS,
physical board timing, measured E62 motor current, efficiency or EMI.
