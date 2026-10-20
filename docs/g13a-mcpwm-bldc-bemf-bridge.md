# G13A — Six-output PWM → Virtual BLDC → BEMF → CMPSS0/ECAP1

## Strict acceptance boundary

This is an **independently configured QTest peripheral/model coupling**,
not original-ELF motor control and **not** native firmware closed-loop.
The original ESCape32 ELF is loaded only as a board image; the QTest
fixture configures MCPWM4, six native PINCM routes, PB13 GPIO gate,
CMPSS0 and ECAP1. It must not be described as guest-authorized drive.

The G12 native firmware reaches its tick loop in a baseline with six
PWM pads isolated and power stage inactive. G13A never overrides
those electrical safety/ownership decisions in guest firmware.

## Data flow

```text
QEMU MCPWM4 AQ/DB six-output READ-ONLY observer (+ validity/running)
    -> PB13 actual PINCM + GPIO DOE/DOUT + six PWM PINCM checks
    -> VirtualBLDC R/L/Ke/Kt/J/B/inertia and explicit 24V test fixture
    -> explicit 3.3V / 1.65V bias / 0.02V per BEMF V analog fixture
    -> bounded, unclipped 12-bit per-phase codes
    -> simulator-only 0x5FFE2000 input (phase U/V/W with validity)
    -> QEMU native CMPSS0 filter -> ECAP1 Input45 CAP1/IRQ
```

Only the six **actually modeled output duty measurements** come
from MCPWM4; neither throttle/command nor target RPM is used.
The virtual motor advances by a bounded number of held PWM periods
with an explicitly given timer frequency. The bridge advances
QEMU virtual time accordingly before posting the sample.

The PB13 GATE GPIO must be powered, output-enabled, set to the
**explicitly selected gate polarity**, **and** PINCM PB13 must
select its GPIO function. Every one of six PWM PINCM words must
match the documented MCPWM4 routes; all six PWM observer channels
must be valid and running. ECAP1/CMPSS0 must be powered and the
native comparator/Input45 mux must actually be selected.
Invalid paths abort before emitting BEMF stimulus; no silent
autostart, overriding of safety controls or artificial capture flags.

The analog transfer is a **fixture**, NOT the electrical schematic:
it currently treats phase BEMF as a bipolar quantity centered at
an explicit midscale bias. A real energized phase terminal may have
common-mode and PWM-switching dynamics, analog attenuation, phase
selection and blanking that differ substantially. Saturation raises
an error rather than silently clipping comparator codes.

## Tests and remaining boundaries

```bash
cd ~/github/escape32-qemu
git pull --ff-only
./build.sh
python3 tests/g13_pwm_motor_feedback.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf ~/github/ESCape32/build-qemu-am13e/AM13E-rev17.3.elf
```

Pass criteria: disconnected gate produces no motion/stimulus; the
QTest-owned six PWM channels are genuinely observed; explicit
VirtualBLDC states produce a valid voltage-derived, not
hand-authored, comparator input; powered/routed CMPSS0 generates
a digital filtered edge, which makes ECAP1 capture an actual
timestamp; invalid gate/pads or PWM state rejects further updates.
Strict mode or unpowered native peripherals must never accept
a phantom output/feedback shortcut (covered by G9/G10 negative tests).

**G13B (OPEN):** Native original ELF must itself enable and use
qualified output pads/gate, generate six PWM waveforms, and consume
its own resulting BEMF/ECAP feedback while scheduling real commutation
with supported motor parameters. None of these firmware ownership,
board/polarity, arm-command, motor or power-stage safety conditions
is supplied by G13A. A true closed-loop PASS additionally requires
repeated native duty/commutation changes causally attributable to
fed-back capture events, not QTest register writes.

## First passing integrated QTest evidence

[CI run 39470700306](https://github.com/cctsao1008/escape32-qemu/actions/runs/39470700306)
completed successfully. It built the pinned original AM13E Rel17.3
application ELF and custom QEMU and passed all G0–G12 regressions
plus the G13A feedback fixture. Actual log:

```text
G13A_ANALOG_SATURATION_REJECTED=PASS
G13A_DISCONNECTED_GATE_ZERO_MOTION_NO_STIMULUS=PASS
G13A_QEMU_MCPWM_TO_MOTOR_TO_CMPSS_ECAP_CAPTURE=PASS rpm=977.04 phase_u_code=2229 CAP1=200013
PASS_G13A_GATE_PAD_AND_INVALID_PWM_FAIL_CLOSED
PASS_G13A_QTEST_ONLY_NO_NATIVE_CLOSED_LOOP_CLAIM
PASS_G12_NATIVE_SYSTICK_PENDSV_THREAD_SHIFT2
PASS_G12_NATIVE_WFI_EXECUTE_IRQ_WAKE_REVISIT_SHIFT2
```

These numbers are consequences of the explicitly chosen
idealized **test motor and analog parameters**; they are not
empirical data for an E62 production motor. In this QTest setup,
a 75% U-high / 75% V-low output was programmed into native QEMU
MCPWM4 model registers. The six-output observer reported this
actual modeled image, the host advanced the motor for 2,000
PWM periods (2ms virtual time), produced a 12-bit voltage sample
(phase U code 2229), and CMPSS0 filtered it into a real
ECAP1 capture (CAP1 200013). There was no software write
to ECAP1 CAP1 or forced comparator/IRQ flag.

**No native closed-loop qualification is implied.** Firmware
must demonstrate its own gate/pad authorization, dynamically
changing six-output AQ/compare image and real response to
captured BEMF before G13B can be considered.
