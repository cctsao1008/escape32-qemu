# E62 G13B3 — Experimental Current-Continuous Host Motor (isolated)

## Scope / hard boundary

This commit adds **a separate host-only** BLDC model. It does NOT
replace `NativePowerCoupledBLDC`, inject analog BEMF into QEMU, alter
ESCape32 Rel17.3, change DShot/ARM/CAP1/TIMG12/PWM/Gate/Trip, or
relax independent 12-sector / 90ms strict rotor acceptance.

Source: `tools/current_continuous_bldc.py`
Host tests: `tests/test_current_continuous_bldc.py`
Fixture: `tools/current_continuous_switch_benchmark.py`

The observed Native SITL WFI trace has **averaged six-output PWM high
ticks**, not exact edge timestamps, switching dead-time or gate
freewheel voltages. It cannot be truthfully converted into a complete
instantaneous switching schedule. The new model **requires** a caller
to supply exact H/L/Z leg states and finite durations; it refuses
passing numeric duty percentages as topologies.

## Explicit idealized switching and diode rules

For each U/V/W leg:

- `H`: high MOS ON, terminal Vbus; current can be positive or
  negative through an ideal bidirectional-on MOSFET
- `L`: low MOS ON, terminal 0V; bidirectional-on MOSFET
- `Z`: both switches OFF; an OPEN phase has endpoint current 0,
  a LOW_DIODE carries **positive** phase current and clamps to
  `-Vf`, a HIGH_DIODE carries **negative** phase current and clamps
  to `Vbus+Vf`

The motor phases share a star neutral with `iU+iV+iW=0`.
Each finite timestep enumerates a small ideal-diode complementarity
active set, constrains unpowered terminals to [-Vf,Vbus+Vf], and
solves equal R/L winding currents with *implicit Euler*. A phase
may conduct a diode even when its MOSFETs are OFF. An open leg may
reach zero current during a step, but the diode zero-crossing time
*inside* that timestep is not reconstructed.

The phase-to-neutral voltage, e/BEMF, torque, and mechanical
acceleration are calculated using the reciprocal pinned experimental
constants (`Ke_elec=.02`, `p=7`, `Kt=.14`). A nonreciprocal
motor constant combination is refused. These synthetic constants
are **not calibrated E62 motor or electrical hardware measurements**.

Crucially, calling `set_switches()` NEVER modifies `iabc` or
instantaneous magnetic energy. There is **no** `I_new=I_old/2`
projection. Conduction and winding currents change only over the
subsequent explicitly specified integration interval.

## Energy bookkeeping

For each implicit-Euler electrical timestep:

    E_bus - E_diode - E_copper - E_BEMF - Delta E_magnetic
      = (L/2) * sum_i (Delta I_i)^2

The RHS is **numerical damping from backward Euler**, NOT physical
diode loss or a hardware efficiency result. Both the numerical loss
and physical diode/copper loss are reported separately.

Mechanical energy, friction and load are also tracked. Total raw
energy residual can remain finite because BEMF uses old angle and
speed while torque uses the new current and backward step of speed.
This still requires timestep convergence and a physical switching
waveform. The test uses an explicit electrical rotor advance guard
(0.35 rad/step, adjustable with explicit parameter).

Even for a perfect reported electrical identity, all these
qualification fields remain false:

    physical_motor_qualified
    real_native_guest_PWM_or_CAP1_qualified
    numeric_timestep_convergence_qualified

## Run host-only tests and a deterministic SYNTHETIC switch fixture

    cd ~/github/escape32-qemu
    git pull --ff-only
    python3 tests/test_current_continuous_bldc.py

    python3 tools/current_continuous_switch_benchmark.py \
      --substeps 1 2 4 8 \
      --output artifacts/g13b3-current-continuous-host-benchmark.json

    python3 - <<'PY'
    import json
    d=json.load(open("artifacts/g13b3-current-continuous-host-benchmark.json"))
    print("Scope:",d["scope"])
    print("Native PWM edges available:",d["actual_native_pwm_edges_supplied"])
    for r in d["results"]:
        e=r["model_energy"]
        print(r["substeps"],round(r["final_rpm"],2),
              e["raw_energy_residual_j"],
              e["backward_euler_electrical_numerical_loss_j"],
              e["forced_current_projection_impulse_energy_j"],
              e["diode_conduction_intervals"])
    PY

The fixture's synthetic sequence is H/L/Z -> Z/H/L -> L/H/Z ->
Z/Z/Z with **explicit 1 microsecond intervals**, subdivided
1/2/4/8. It is **not** a replay of the real ESCape32 85.875ms
PWM transition, and its RPM must not be compared to Native 773 WFI
RPM as if these were the same drive commands.

## Gate for any future native integration

Do NOT silently feed this model the existing averaged Native PWM
image; doing so would invent diode conduction, which is physically
unsafe evidence. Before coupling to original Native WFI feedback,
supply and verify actual high/low MOS switching state timing,
including turn-off and deadtime, or a separately grounded equivalent
averaged switching/freewheel network. Then perform independent
convergence, energy/passivity and CAP1/TIMG12 timing checks.

Even after a real switching timeline is provided, preserve unchanged
original Guest firmware and independent Strict Rotor Gate. The host
fixture results alone are NOT Native Motor Stability PASS.
