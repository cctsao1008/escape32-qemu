# G11 — Cortex-M33 Exception Lifecycle Validation

## Problem statement and evidence

On the original native AM13E Rel17.3 ELF, G1/G10D reaches the
runtime IRQ release barrier, then reports `CFSR=0x00040000`
(INVPC UsageFault, escalated to HardFault). Earlier precise MMIO
BusFaults at MCPWM4 `0x40014010` and ECAP1 `0x4044102A`
have been resolved by distinct firmware/model changes. This is a
new CPU/IRQ exception-return investigation, not a motor feedback PASS.

The native code for `am13e_app_motor_runtime_enable_interrupts()`
finishes its safety and priority checks, then executes `DSB`, `ISB`,
`irq_barrier_released=1`, and **`CPSIE i`**. The exact instruction
address is resolved from the supplied ELF symbol and checked for the
Thumb `0xB662` opcode: no fixed PC or replacement firmware is used.

## G11A — Passive architectural observer

The **non-silicon**, read-only address `0x5FFE3000` is available
only under `esc-sim=on`; the strict profile rejects access.
All accesses are 32-bit aligned, and every write returns `MEMTX_ERROR`.

| Offset | Meaning |
|---|---|
| `+0x00` | `0x47313101`, observer version |
| `+0x04` | PRIMASK |
| `+0x08` | BASEPRI |
| `+0x0C` | FAULTMASK |
| `+0x10` | CONTROL |
| `+0x14` | MSP |
| `+0x18` | PSP |
| `+0x1C` | active IPSR/exception number |
| `+0x20` | core LR |
| `+0x24` | core PC |
| `+0x28` | core xPSR |

MSP and PSP account for Thread/Handler mode and CONTROL.SPSEL.
This observer reads QEMU CPU state directly without synthesizing
interrupts or changing exception-return handling. G11A QTest checks
PRIMASK=1 on handoff, vector-derived MSP/PC, Thumb state and rejection
of attempted writes. This is architectural-state **observation**, not
a CPU architectural conformance test.

## G11B–G11D — Original-ELF exception trace

`tests/g11_exception_lifecycle.py` creates two fresh QEMU processes
from the same original ELF with the same `-icount shift=10` setup.
The ELF's verified SDK delay loop is executed by QEMU using temporary
return-address GDB breakpoints; no guest timebase is skipped.

- Single-step variant: stop before native `CPSIE i`, snapshot
  PRIMASK/BASEPRI/FAULTMASK/CONTROL/MSP/PSP/IPSR/ICSR, then
  single-step across the release and record IRQ/exception transitions.
- Continuous variant: stop at that same native `CPSIE i`, install
  temporary GDB breakpoints at the original `SysTick_Handler`,
  `PendSV_Handler`, `HardFault_Handler` and the next Thread PC, then
  `continue` from the release. Record which path is actually taken.
- Both variants use QEMU 6.2's **built-in `-d int`** exception
  logger. Full `CPU_LOG_INT` text is saved to separate artifact files;
  output includes exception-return magic, tail-chaining and integrity
  failures when QEMU logs them.

Run against your **current native ELF**:

```bash
cd ~/github/escape32-qemu
git pull --ff-only && ./build.sh
python3 tests/g11_exception_lifecycle.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf ~/github/ESCape32/build-qemu-am13e/AM13E-rev17.3.elf \
  --mode both --startup-steps 32768 --post-steps 512 \
  --artifact-dir artifacts
```

**Acceptance boundary:** A `PASS_G11_DIAGNOSTIC_INSTRUMENTATION_ONLY`
means that a non-invasive native code and CPU-state comparison ran.
It **does not** mean the INVPC is fixed or that Exception Return,
normal boot, runtime motor control or physical output is qualified.
An INVPC after `CPSIE i` must be traced to actual EXC_RETURN magic,
the active/stacked IPSR, MSP/PSP frame and the CPU's integrity-check
reason before deciding whether the defect belongs to the guest,
QEMU Cortex-M33 modeling, timer/priority emulation or the GDB test
mode. Do not suppress IRQ delivery or bypass the Fault as a fix.
