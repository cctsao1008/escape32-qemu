# G10 — ECAP1 / CMPSS0 BEMF feedback (ESC-SIM)

## Scope and source

This is a functional, explicitly opt-in digital peripheral model for the
original ESCape32 Rel17.3 firmware targeting TI AM13E23019. Register
offsets, field definitions and APIs follow TI AM13E2x SDK
`hw_ecap.h`, `hw_cmpss_lite.h`, `dl_ecap.c`,
`dl_cmpss_lite.c`, and `hw_ints.h`. The firmware's
motor-control/commutation algorithm is not modified.

Only `-machine am13e23019,esc-sim=on` enables modeled access.
Default strict mode rejects unimplemented ECAP1/CMPSS0 transactions.
Hardware timing, comparator analog behavior and power-stage safety
are **not** established by simulator tests.

## G10A — Native ECAP1 registers

ECAP1 base address `0x40441000`: TSCTR +0x00, CTRPHS +0x04,
CAP1–4 +0x08..+0x14 (32-bit), ECCTL0 +0x24 (32-bit), ECCTL1
+0x28 and ECCTL2 +0x2A (16-bit), ECEINT +0x2C, ECFLG +0x2E,
ECCLR +0x30, ECFRC +0x32 (16-bit), ECAPSYNCINSEL +0x3C.
Unknown offsets and illegal sizes return `MEMTX_ERROR`.
`SYSCTL.PWREN_MCPERIPH` bit4 is required; accesses are rejected
before power-on. NVIC IRQ30 is wired for ECAP1.

## G10B — Real virtual-time capture/interrupt engine

TSCTR advances only while the ECAP1 clock is enabled. This
functional simulator uses a declared 100 MHz timebase, i.e.
10 virtual ns per counter tick, and models START/STOP, rollover,
counter overflow, event timestamp CAP1–CAP4, event polarity,
CAPLDEN, IRQ enables and W1C flags. ECEINT by itself does not
generate an interrupt; ECFRC forces flags but does not modify CAP.
No capture timestamp or CEVT flag is generated merely because
time passes.

## G10C — CMPSS0 high comparator → ECAP1 Input 45

CMPSS0 base `0x40460000` supports the relevant SDK high-comparator
register subset, power bit10, phase-input selection via SYSCTL
HP mux, high DAC active/shadow and a bounded virtual majority-filter
transition. DAC PWM-synchronized activation follows actual MCPWM4
counter-zero events. ECAP1 Input 45 accepts only qualified output
transitions with the programmed edge polarity and powered devices.

A **test-only** non-silicon stimulus aperture at `0x5FFE2000`
accepts three 32-bit phase sample words: offsets 0, 4 and 8
for phases U/V/W. Bits 11:0 supply a normalized 12-bit sample;
bit16 marks validity. This input does **not** simulate motor back-EMF
from the six PWM gate outputs. An autonomous virtual BLDC plant and
physical board polarity/gate qualification remain out of scope.

## G10D — Original ELF evidence

Run `./test.sh /path/to/AM13E-rev17.3.elf` for native MMIO tests,
including powered-off negative cases, no-phantom edge conditions,
short filter pulses, wrong routes and strict-mode refusal.

To test actual guest-executed startup (not host pre-seeded registers):

```bash
python3 tests/g1_handoff.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf ~/github/ESCape32/build-qemu-am13e/AM13E-rev17.3.elf \
  --esc-sim --timed-steps --fast-delay-loops \
  --startup-steps 32768 --require-pwm4-init --require-ecap1-init
```

The native test checks ECAP1 power, Input 45, running counter and
CAPLDEN **actually enabled by at least one native ECCTL1 MMIO write**.
The read-only, ESC-SIM-only history register at `0x5FFE200C` has
bit0=CAPLDEN ever enabled since ECAP1 reset, and bits31:16=count of
0->1 enable transitions. No physical AM13E register exists there.
Only a write to the genuine ECAP1.ECCTL1 with bit8 changing 0->1
can update that history; the test-only register cannot be written.

The first G10D test used GDB sampling every 16 instructions. A WSL
build could set and clear ECCTL1.CAPLDEN within that sampling period
so its final ECCTL1=0 was incorrectly reported as an initialization
failure. The native-write observer avoids this compiler/step-phase
dependence while keeping source/ELF unmodified. A legitimate safety
shutdown can clear CAPLDEN without erasing historical initialization.
The history is cleared by QEMU machine/ECAP1 reset, not by bit8=0.

An initial firmware trace on the G10 model passed the previous
`BFAR=0x4044102A` ECAP1 initialization BusFault, then encountered
a **new** `CFSR=0x00040000` INVPC UsageFault with stacked
`PC=0x0000900A`. This is a distinct open exception-return issue.
Neither G10D nor any model-only PASS is a claim of normal firmware
startup, real motor motion, closed-loop response or hardware readiness.

## Regression files

- `machine/am13e23019.c` and `machine/am13e_motor_feedback.inc`
- `tests/g10_feedback.py` (independent G10A–C QTest)
- `tests/g1_handoff.py --require-ecap1-init` (G10D original ELF)
- `.github/workflows/esc-sim-regression.yml`
