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
  --require-no-invpc --artifact-dir artifacts
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
