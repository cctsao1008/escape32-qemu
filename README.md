# escape32-qemu

ESCape32 Rel17.3 on TI AM13E23019 — minimal QEMU 6.2.0 platform.
QEMU remains pinned as an upstream Git submodule; `./build.sh` applies
local integration only inside ignored `.build/qemu-src`.

## Build and test (WSL / Ubuntu)

```bash
sudo apt install build-essential pkg-config libglib2.0-dev libpixman-1-dev libfdt-dev ninja-build meson python3
git submodule update --init qemu
./build.sh
./test.sh ~/github/ESCape32/build-qemu-am13e/AM13E-rev17.3.elf
```

**G0:** 512 KiB Flash, 128 KiB SRAM, shared Bank 3 alias at
`0x20018000` / `0x00C18000`; QTest checks both directions and
real ELF vector bytes without running guest instructions.

**G1 candidate:** models the state **after** ESCape32's Bootloader
handoff, not the AM13E silicon power-on reset. The CPU is a
`cortex-m33-am13e` variant without the Security Extension,
VTOR is initialized to `0x6000`, MSP/PC are loaded by QEMU from
the original ELF vectors, and the board handoff reset callback
sets PRIMASK=1, which the application expects. The G1 test uses
QEMU's built-in GDB remote stub to read initial CPU registers,
VTOR and ID_PFR1, then single-steps the original Reset_Handler.

**Boundaries:** no Bootloader/Cfg.id validation; no SYSCTL/PLL/FRI
register model; no motor plant or validated real-time control.
A G1 test pass does not mean that the application's initialization,
clock checks, or safety gates have passed. PRIMASK=1 is set by the
model callback but is not independently observed by the GDB test.

Reference: AM13E230x TRM (SPRUJF2B) and ESCape32
`am13e-port-v2`, commit `0f21de6`.

### Bounded G1 Startup Trace (diagnostic, optional)

Once the default `./test.sh ELF` passes, trace up to 4096 original
Reset_Handler instructions without modifying the Firmware:

```bash
python3 tests/g1_handoff.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf ~/github/ESCape32/build-qemu-am13e/AM13E-rev17.3.elf \
  --startup-steps 4096
```

The test prints sampled PCs, frequent PCs and the recent PC history.
It stops early if the actual HardFault vector is entered. A bounded
trace is diagnostic only; no peripherals or fabricated ready bits
are added, and normal loop/stall behavior is not labeled PASS.

## G2a: SYSCTL Reset Snapshot (first increment; not G2 scheduler PASS)

`0x400B0104` is `SYSCTL.SOCLOCK.MCLKCFG`, offset `0x1104`
from `SYSCTL_BASE=0x400AF000`. Reading this register was the precise
BusFault captured during G1 startup trace. G2a maps a deliberately
minimal SYSCTL aperture; the two **read-only** modeled reset values are:

| Register | Address | Explicit reset fields | G2a value |
| --- | --- | --- | --- |
| MCLKCFG | `0x400B0104` | MCLKDIVCFG=7; USEHSCLK=0 | `0x07000200` |
| CLKSTATUS | `0x400B0204` | SYSPLLOFF=HFCLKOFF=HSCLKSOFF=1; SYSOSCFREQ=0 | `0x00007000` |

TRM reset fields marked `X` are represented as 0 **for this emulator
profile only**. All other SYSCTL reads and all SYSCTL writes are rejected
with `MEMTX_ERROR` and the first invalid transaction is logged as
`G2_UNMODELED_SYSCTL`. In particular, this does **not** simulate XTAL,
SYSPLL lock, FRI Flash wait states, or real 200 MHz clock switching.
A subsequent HardFault is expected until its next reached register
has an explicit model. The existing G1 one-step check remains valid.

Source: AM13E230x TRM SPRUJF2B §§3.14.2.12, 3.14.2.34; TI SDK
`hw_memmap.h`, `hw_sysctl.h`. `PASS_G2A` is **only** a reset-register
readback test, not the G2 Scheduler acceptance gate.

## G2b: FRI Flash Read Interface FRDCNTL

The G1 extended startup now reaches `0x00C18018` executing copied
TI `.TI.ramfunc`. Its precise BusFault has `BFAR=0x40029000`,
which is `FRI_BASE (0x40028000) + FRDCNTL (0x1000)`.

G2b models **FRDCNTL only**, reset `0x02000201` as specified by
AM13E230x TRM SPRUJF2B §13.7.2.1. The documented fields
`WS0_MODE[0]` and `RWAIT[11:8]` are writable and readable.
All other register bits retain the reset image; undocumented
reserved R/W bits are not assigned invented functionality.
Writes to other FRI offsets and reads from other FRI offsets return
`MEMTX_ERROR` (first occurrence logged as `G2_UNMODELED_FRI`).

QTest validates the actual TI DriverLib sequence for
`DL_FRI_setReadWaitStates(3)`:
`0x02000201 → 0x02000200 → 0x02000300`.

**Limitations:** no simulated Flash access latency, wait-state
enforcement, nine-cycle return flush, SYSPLL transitions, or motor
feedback. G2b's PASS is a register-model test, *not* a claim that
the product FW has completed clock initialization or qualified 200MHz.

Sources: TRM SPRUJF2B §13.5.6 & §13.7.2.1 and SDK
`hw_memmap.h`, `hw_fri.h`, `dl_fri.c`.
