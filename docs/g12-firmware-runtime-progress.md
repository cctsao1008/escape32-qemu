# G12 — Native Firmware Runtime Progress & QEMU Timing Differential

## Purpose

G11 closed an independent QEMU 6.2 Cortex-M33 EXC_RETURN integrity
mismatch, but a G11 sample at `icount shift=10` still stopped inside
SysTick (IPSR 15). That observation by itself is **not** proof that
the ESCape32 main loop is hung, nor proof of working closed-loop ESC
runtime. G12 measures events without changing any firmware data, IRQ
priorities, PRIMASK, stack or peripheral register state.

## Timebase interpretation

QEMU `-icount shift=N` advances virtual time by `2^N ns` for each
translated instruction (subject to QEMU device and idle-time behavior).
This is **not** a cycle-accurate 200 MHz AM13E CPU model; CPI, buses,
interrupt latency and peripherals are not modeled as silicon timing.
ESCape32 configures a 16 kHz SysTick with 62.5 µs nominal period.

| shift | QEMU virtual ns/instruction | Nominal instructions/tick |
|---|---:|---:|
| 2 | 4 | 15,625 |
| 4 | 16 | 3,906.25 |
| 10 | 1,024 | 61.04 |

At shift=10, an ISR needing more than roughly 61 QEMU guest
instructions per 16 kHz tick will see the next tick pending. This
can create an artificial continuous-ISR schedule. Shift=2 is
a *comparison fixture*, not an assertion of true 200 MHz execution.

## Native event evidence

`tests/g12_runtime_progress.py` starts independent QEMU instances for
each shift, with the original ELF and `esc-sim=on` only. G11's verified
step-to-CPSIE routine locates the original firmware instruction via
ELF symbol and machine-code verification, executing the SDK delays
through the CPU. It then arms one-shot *hardware-independent GDB
breakpoints* at the native:

- `SysTick_Handler` and `PendSV_Handler` entries;
- instruction immediately after native `CPSIE i` (Thread Mode);
- actual `wfi` opcodes within the disassembled
  `am13e_rel17_app_main` symbol;
- `HardFault_Handler`.

Each run continues **genuine guest execution** until a hit or a
bounded GDB Ctrl-C pause. The console and JSON artifact record
observed PCs, IPSR, PRIMASK, `SCB->SCR` (SLEEPONEXIT), ICSR, CFSR,
HFSR and elapsed wall-time **bounds**. The QEMU CPU `-d int` log is
also preserved; its exception 14/15 entry and successful return
counts are derived from actual QEMU messages, not PC sampling.

Importantly, native Rel17 can execute `WFI` before sensor readiness
or in its control loop, and explicitly sets `SCB_SCR_SLEEPONEXIT`
when entering the runtime tick path. Thus a WFI breakpoint alone
does not establish motor-control loop advancement, and a Handler
snapshot under SLEEPONEXIT need not prove starvation.

## Run

```bash
cd ~/github/escape32-qemu
git pull --ff-only
./build.sh
python3 tests/g12_runtime_progress.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf ~/github/ESCape32/build-qemu-am13e/AM13E-rev17.3.elf \
  --shifts 2 10 --slice-ms 80 --max-stops 6 \
  --require-no-invpc --require-shift2-progress \
  --artifact-dir artifacts
```

`--require-thread`, `--require-pendsv`, and `--require-wfi` are
**opt-in gates**, to be enabled in CI only once the native
firmware and simulator are shown to meet them. Default output
`PASS_G12_BOUNDED_NATIVE_RUNTIME_DIAGNOSTIC_ONLY` means the
measurement ran; it must **never** be represented as complete
thread scheduling, firmware startup, control-loop health or a
physical real-time performance claim.

The next step after evidence collection is to decide whether any
blocked progress is due to (a) artificially small icount instruction
budget, (b) intended SLEEPONEXIT/WFI behavior, (c) absent model of
a real required sensor/event, or (d) an actual architectural defect.
Only evidence-backed software or peripheral-model changes qualify.

## First native comparison (before WFI extension)

[CI run 39464794010](https://github.com/cctsao1008/escape32-qemu/actions/runs/39464794010)
reproduced the same pinned native firmware at two timebases:

- **shift=2**: `SYSTICK_ENTRY IPSR=15`, then `PENDSV_ENTRY IPSR=14`,
  then `THREAD_AFTER_CPSIE IPSR=0`; no HardFault or INVPC. QEMU's
  actual `CPU_LOG_INT` messages recorded three SysTick entries and two
  PendSV entries during this bounded run.
- **shift=10**: 2,500 SysTick entries and 2,499 attempted exception
  returns in an 80ms host-time diagnostic slice. No PendSV or native
  Thread PC breakpoint was reached within that slice. CFSR and HFSR
  remained zero; this was not a new Fault.
- The previous test terminated early after returning to Thread,
  so **WFI was not yet tested**. This has now been extended:
  after the first Thread return, the test continues (bounded)
  toward the actual native Rel17 WFI instructions.

The observed shift=2 sequence is now an opt-in **mandatory CI gate**
`--require-shift2-progress`. The shift=10 result remains a
**timebase-dependent observation**, not a permanent assertion that
the original firmware must starve when the simulator timing changes.
A WFI hit is recorded but is not asserted until its interpretation
(sensor wait versus main motor loop) is established.

## Native post-Thread RSTCAUSE BusFault

The WFI-extended G12 run
[39466570185](https://github.com/cctsao1008/escape32-qemu/actions/runs/39466570185)
proved that native SysTick (IPSR 15), PendSV (IPSR 14) and Thread
(IPSR 0) execute at shift=2, then encountered a **new** precise
BusFault before WFI:

```text
CFSR=0x00008200 BFAR=0x400B0220
stacked_PC=0x000075E6
am13e_app_motor_reset_flags():
  ldr.w r3, [r3, #0x220]
QEMU: G2_UNMODELED_SYSCTL read 0x400b0220
```

Texas Instruments AM13E SDK `hw_sysctl.h` defines the native
`SYSCTL->SOCLOCK.RSTCAUSE` at SYSCTL base + 0x1220. Its
`ID[4:0]` field is **read-to-clear**; DriverLib
`DL_SYSCTL_getResetCause()` reads it. This is unrelated to the
already repaired Cortex-M33 INVPC fault.

QEMU now models exactly that 32-bit register: it preserves a
valid reset-cause ID and clears it on read; guest writes remain
rejected. The model's Bootloader-handoff default is
`NORST=0` because there is no proven prior silicon reset source.
A **simulator-only explicit** machine option
`esc-sim-reset-cause=0xe` can supply a TI documented WWDT0
reset-history fixture for QTest. This option does not invent a
watchdog trip in the normal simulation and is disallowed in
strict mode. Reserved enumerations and unmodeled SYSCTL registers
remain rejected.

`tests/g12_reset_cause.py` covers default NORST, read-to-clear
from nonzero fixture, write rejection and strict no-phantom
semantics. The **native** continuation beyond the previous
BusFault and WFI still require a subsequent CI result; neither
model compilation nor a QTest pass implies normal motor startup.
