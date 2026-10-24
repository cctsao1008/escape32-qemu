# E62 G13B3M — Deterministic Frozen Native PWM Integration Replay

## First reproduce the guest’s existing sampled-hold model

The original ESCape32 Rel17.3 ELF, its WFI checkpoints and actual
six-pin PWM high tick observations are read from an **existing Native
SITL trace**. Replay happens in a separate host Python process: no
QEMU, Guest, DShot, CAP1, TIMG12, altered BEMF, forced IRQ or live analog
stimulus is involved.

Motor parameters are taken from the trace's **embedded** pinned
SIM_ONLY model profile. Pre-profile or unqualified traces are refused.

**Essential guard:** with one substep per interval, replay must match
the original sampled model's saved motor RPM, electrical angle and
three-phase current at **every** WFI. If it cannot, report fails closed
instead of calling n=2/4/8 differences "convergence".

For each Native WFI, if the original PWM image was unchanged,
replay the original integrated ECAP delta. Split this bounded original
dt into N=1/2/4/8 numerical steps using exactly that PWM duty image.
If PWM image CHANGED, the native timeline did not integrate the
unknown PWM-transition interval. The replay **also skips it**; it
never invents an interpolation or switching waveform.

This reproduces, rather than fixes, the current discontinuity at the
first integration interval of a newly sampled source/return pair.

## Execute against retained Reciprocal Energy Trace

    cd ~/github/escape32-qemu
    git pull --ff-only

    python3 tests/test_native_frozen_pwm_convergence.py

    python3 tools/native_frozen_pwm_convergence.py \
      --trace artifacts/g13b3m-reciprocal-energy-trace.json \
      --substeps 1 2 4 8 \
      --output artifacts/g13b3m-reciprocal-frozen-convergence.json

Look at:

- `same_source_step1_replay_match`: must be true, or replay fails.
- `neighboring_resolution_differences`: compare 1→2, 2→4,
  and 4→8 max RPM, rotor electrical angle and phase-current deltas.
- Per resolution `energy.raw_energy_balance_residual_j`,
  `energy.integration_residual_excluding_topology_impulses_j`,
  `energy.topology_projection_impulse_energy_j`.
- Per resolution final rotor speed and deviation against the
  **recorded** Native trajectory, not only against N=1 replay.

A 9-reversal result recorded in the original Native trace must NOT
be substituted with the replay's reprocessed RPM sequence. This is
an **open-loop frozen-input replay** without updated firmware response.

The original Native trace contains only the successful WFI 1..773.
Its failed 774th analog sample is not replayed, and its partial
exception is not discarded.

## Interpretation

If the N→2N state deviations and non-impulse energy residuals decrease
under refinement, there is evidence of timestep sensitivity. It does
not certify a physically correct model or fix the 0.514J missing
commutation current/freewheel dynamics. If refinement does not
converge, do not change Guest firmware on the basis of host model RPM.

The PWM path remains sampled-high-tick averaged, not actual switching
edge capture. Unknown physical commutation windows are not reconstructed.

The tool reports these as `false` unconditionally:

    numerical_convergence_qualified
    physical_motor_qualified
    independent_strict_gate_executed

The original G13B3M strict rotor gate remains unchanged and FAIL is
still a valid outcome.
