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

## G2c: SYSCTL MCLKCFG Divider-only Write Model

The G1 extended trace reached `stacked_PC=0x00009146` with a precise
BusFault at `0x400B0104` (SYSCTL.MCLKCFG), after completing the
FRI `RWAIT=3` sequence. The next genuine firmware operation is
`DL_SYSCTL_setMCLKDivider(DL_SYSCTL_MCLK_DIV_2_DIV_4)`.
TI DriverLib performs a full-word read-modify-write on
`MCLKCFG[26:24]`, mask `0x07000000`. Allowed encodings are
`0,1,3,5,7`; the reset/firmware-selected divider is 7.

The G2c model provides a **stateful read/write divider field**.
All other MCLKCFG fields retain their prior values, including
`USEHSCLK[16]`, which remains unsupported and returns MEMTX_ERROR
if changed. `CLKSTATUS` remains the reset snapshot; no source-switch
or fabricated PLL lock event. QTest verifies legal transitions,
the reset status, and rejection of a source change.

**G2c PASS is a divider-register semantic check only.** A subsequent
HardFault is expected when the startup reaches its next unmodeled
SYSCTL register. Evidence: AM13E230x TRM SPRUJF2B §3.14.2.12;
TI SDK `dl_sysctl.h` / `hw_sysctl.h`; G1 fault trace.

## G2d: SYSCTL.XTALCR Control Bits (not oscillator readiness)

The G1 trace after G2c reaches a precise BusFault at
`BFAR=0x400B0474`, from `stacked_PC=0x00009246`. This address is
`SYSCTL_BASE (0x400AF000) + XTALCR (0x1474)`, as defined in TI SDK
`hw_sysctl.h`. TRM SPRUJF2B §3.14.2.73 specifies reset value
`0x00000001`; bit 0 `OSCOFF` = 1, bit 1 `SE` = 0.

G2d adds stateful **read and write** of `XTALCR.OSCOFF` and
`XTALCR.SE`. All other bits remain at zero; changes to reserved
bits are rejected with `MEMTX_ERROR`. Clearing OSCOFF is an
**oscillator-enable request only**: `CLKSTATUS` stays at reset
`0x00007000`; neither HFCLKGOOD nor any PLL Ready is manufactured.
The initial state is restored on machine reset.

`tests/g2_xtalcr.py` exercises reset, crystal/single-ended settings,
enable request with unchanged clock status, and reserved-write rejection.

Next: implement the adjacent startup-monitor and HSCLKEN register
semantics, then a virtual-time oscillator readiness transition only
after the documented startup interval and actual enable request.
No hardware, host wall-clock sleeps, or firmware patches are used.

## G2e: SYSCTL.HSCLKEN Control Requests (not oscillator / PLL lock)

G2d's extended trace now reaches `stacked_PC=0x00009272` and a
precise BusFault at `BFAR=0x400B0108`. TI SDK `hw_sysctl.h` and
TRM SPRUJF2B §3.14.2.13 identify that address as SYSCTL.HSCLKEN
(offset `0x1108`). The TRM gives an overall reset value of
`0000XXXXh`; the documented `USEEXTHFCLK[16]` and
`SYSPLLEN[8]` fields both reset to 0. For unknown reserved reset
bits the emulator chooses zero, not a silicon-accurate claim.

G2e makes those two documented bits read/write stateful. All other
fields are preserved, and attempted changes return `MEMTX_ERROR`.
`USEEXTHFCLK=1` means request external digital HFCLK_IN as source.
`SYSPLLEN=1` requests PLL enable, but no PLL-lock/XTAL-good event is
produced. `CLKSTATUS` remains at its G2a reset snapshot.

`tests/g2_hsclken.py` exercises reset, both control requests, rejected
reserved writes, and confirms no ready/status changes.

**This is not Clock State Machine acceptance.** G2f still needs
`HFCLKCLKCFG` startup-time/monitor controls and deterministic QEMU
virtual-time transitions. No hardware and no firmware changes.

## G2f: HFCLKCLKCFG Configuration Registers Only

After G2e the guest enters the TI clock setup routine and faults at
`0x400B0110`, with `stacked_PC=0x0000927e`. This is
`SYSCTL.HFCLKCLKCFG` offset `0x1110` as defined in SDK
`hw_sysctl.h`, TRM SPRUJF2B §3.14.2.15.

The reset pattern is `1XXXXX00h`. The model explicitly sets
`HFCLKFLTCHK[28]=1` and `XTALTIME[7:0]=0`, using zero for
unknown/reserved bits (not claiming actual silicon readback).
It supports stateful read/write RMW on **only** those two documented
fields. A request to change any other field returns `MEMTX_ERROR`
and does not change the register.

`tests/g2_hfclkcfg.py` checks reset `0x10000000`, programs
`XTALTIME=156` (~9.984ms nominal), changes the monitor control,
rejects a reserved-bit write, and proves that `CLKSTATUS` has not
been incorrectly changed to GOOD. G2f deliberately does **not**
simulate oscillator startup time, monitor success, or PLL readiness.

**Next architecture step:** implement timed HFCLK state transition
using QEMU virtual-time clocks, conditional on XTAL enable/source,
monitor setup, and elapsed startup interval. Avoid host sleep
or a fixed GOOD-bit response.

## G2g: Explicit Virtual XTAL Fixture, deterministic startup time

G2f no longer BusFaults. The original Startup enters the bounded
`wait_clock_good(HFCLKGOOD)` loop at `PC=0x90ee..0x90fc` because
`CLKSTATUS` remains in its reset state. G2g does **not** unconditionally
return GOOD; it introduces a virtual crystal input explicitly selected
with `-machine am13e23019,xtal-present=on`. Default is OFF.

When the fixture is enabled, and XTALCR transitions OSCOFF:1→0,
HSCLKEN selects XTAL (USEEXTHFCLK=0), and the SDK monitor bit
HFCLKCLKCFG.HFCLKFLTCHK[28]=1, the model removes HFCLKOFF and
HSCLKSOFF and schedules a single QEMU_CLOCK_VIRTUAL timer at
`XTALTIME × 64,000 ns`. At the deadline, the fixture reports
HFCLKGOOD=1 and maintains SYSPLLOFF=1, without claiming any actual
oscillator waveform or silicon validation. Disabling XTAL cancels the
event and restores OFF. There is no PLL model or motor model.

SDK `hw_sysctl.h` and `DL_SYSCTL_enableHFCLKStartupMonitor()`
set bit 28 to **1** for monitor enable. The prose in TRM
SPRUJF2B §3.4.4.2.2 ambiguously says "clear" to enable, whereas
the bit field table §3.14.2.15 and SDK define `1` as enabled.
The model follows the actual compiled firmware and SDK bit encoding.

Run `./test.sh path/to/AM13E-rev17.3.elf` to exercise:
- No virtual crystal (default and explicit OFF): no manufactured GOOD.
- Explicit virtual crystal: after enable, at 9,983,999 ns remains
  pending, at 9,984,000 ns becomes GOOD.
- Disable, restart, cancel before deadline: no stale timer event.

All transitions use QTest `clock_step` on the QEMU virtual clock,
not `sleep` or a host wall clock. The fixture assumes a successful
clock startup *only when explicitly requested*; absent fixture
does **not** simulate oscillator-failure detection latency.

The GDB trace supports optional `--xtal-present` (default off).
Unlike QTest's `clock_step`, GDB single-step timing is not itself a
deterministic virtual-time/cycle-accuracy test.

### Timed GDB diagnostic stepping

QEMU 6.2 defaults its GDB single-stepping flags to
`SSTEP_ENABLE|SSTEP_NOIRQ|SSTEP_NOTIMER`. Thus the regular
`--startup-steps` trace alone may never deliver a virtual
clock timer. The optional `--timed-steps` probes
`qqemu.sstepbits`, explicitly applies `Qqemu.sstep:1`
to enable timers/IRQs, and starts QEMU with
`-icount shift=13,sleep=off,align=off`.

```sh
python3 tests/g1_handoff.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf ~/github/ESCape32/build-qemu-am13e/AM13E-rev17.3.elf \
  --xtal-present --timed-steps --startup-steps 16384
```

At shift=13, each guest instruction is charged 8192 virtual
nanoseconds; this **deliberately accelerates** simulated time and
does **not** model 200MHz CPU cycles. Results show control-flow
progress only. Use the G2g QTest clock_step cases for actual timer
boundary validation.
