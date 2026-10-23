# G13B3M: Host-side Numerical Energy and Fail-Closed Native Diagnostics

## What this proves — and what it does not

The original ESCape32 Rel17.3 Guest firmware, TI SDK, QEMU AM13E
peripherals, PA26 DShot/CRC/250ms ARM, CAP1 -> TIMG12 commutation,
PWM/Gate/Trip, motor constants, ADC frontend gain and independent 12-sector
90ms rotor-direction strict gate remain UNCHANGED.

The host plant still uses a sampled-hold two-terminal Euler integration.
The floating phase is modeled open; a change of source/return pair
**projects** the old three-phase current into the new branch. That
instantaneously discards stored magnetic energy without modeling
freewheeling, diode conduction or switching transients.

This phase explicitly **measures** that discontinuity. It does not
pretend it is physically correct, subtract it to obtain a motor PASS,
or invent any Guest hardware event.

## Per-integration bookkeeping

For each model advance, in joules:

    E_in - E_Cu - E_visc - E_load - Delta E_kin - Delta E_mag
      = raw_energy_balance_residual

    integration_residual_excluding_topology_impulses
      = raw_energy_balance_residual + topology_projection_impulse

The signed topology impulse is:

    Delta E_topology =
      (L/2) * sum(phase_current_after_projection ^ 2)
      - (L/2) * sum(phase_current_before_projection ^ 2)

The copper-loss integral uses a linearly interpolated branch current
over the Euler step; kinetic and magnetic terms are endpoint energy
differences. Their residual is a diagnostic of time discretization,
BEMF/torque evaluation order and model consistency, not an accepted
convergence bound.

The open-bridge case also records the implicit reset-to-zero magnetic
energy jump. Both **raw** and **impulse-separated** residuals are kept;
the projection is never silently dismissed.

The online ledger keeps finite cumulative totals, every integration
interval count, peak per-step residual and the first 12 topology-event
examples. At each native Guest WFI, telemetry reuses the *existing*
Host plant state and ledger. No extra Guest MMIO observations are made.

All reports always retain:

    numerical_energy_balance_qualified = false
    commutation_current_continuity_qualified = false
    physical_motor_calibrated = false

This work does NOT qualify numerical solver convergence, PWM switching
transients, hardware motor efficiency/current or actual rotor stability.

## Failed Native WFI behavior

On a native Motor Plant or Analog Frontend exception, the probe records:

- The failed WFI and **last fully accepted/injected WFI** separately.
- Original Guest CAP1/TIMG12 audit totals and pending event.
- Original Guest duty/timer diagnostics (read-only).
- Rotor direction count from last complete feedback WFI, not null.
- Energy ledger including the failed step when already integrated.
- Unclipped BEMF phase voltages, attempted analog input voltage and
  overrange phase(s), using the original 3.3V / 1.65V / 0.02 V/V fixture.
- Structured exception reason, e.g. ANALOG_FRONTEND_SATURATION.
- A partial JSON trace with PARTIAL_EXCEPTION and original exception.

No saturation clamp, fake CAP1, Guest SRAM writes, extended-gate bypass
or manufactured motor trace sample is permitted.

## Host-only regression tests

    cd ~/github/escape32-qemu
    git pull --ff-only
    python3 tests/test_native_model_energy_balance.py
    python3 tests/test_native_motor_reciprocity.py
    python3 tests/test_g13b3_native_power_coupled.py

## Rerun the opt-in Reciprocal motor, distinct artifacts

A retained pre-instrumentation trace cannot be retroactively turned
into a per-integration energy ledger: only sampled end states exist
there. Rerun the same GCC15 ELF with identical parameters and new
artifact names:

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
      --artifact artifacts/g13b3m-reciprocal-energy.json \
      --sitl-trace-output artifacts/g13b3m-reciprocal-energy-trace.json \
      2>&1 | tee artifacts/g13b3m-reciprocal-energy.log
    echo "NATIVE_EXIT=${PIPESTATUS[0]}"

An original strict failure is expected to remain visible and is NOT
considered success. A partial trace should still be written when an
analog exception triggers.

## Independently inspect accounting and failure evidence

    python3 tools/native_model_energy_report.py \
      --trace artifacts/g13b3m-reciprocal-energy-trace.json \
      --output artifacts/g13b3m-reciprocal-energy-report.json

The report verifies arithmetic closure and per-WFI provenance. Its
`audit_arithmetic_consistent=true` means only that the **reported
bookkeeping algebra** matches. It is NOT a full physical energy
conservation proof and NEVER executes or passes the rotor strict gate.

Do not reuse the old G13B3M strict PASS criterion merely because this
ledger reports a zero, small, or separated residual. The original
`native_extended_run_gate.py` is untouched.
