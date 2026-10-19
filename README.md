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
`-icount shift=10,sleep=off,align=off`.
QEMU v6.2.0 caps the shift at 10 (`softmmu/icount.c`,
`MAX_ICOUNT_SHIFT=10`); the previous diagnostic-only `shift=13`
failed at process startup and did not run the ELF.

```sh
python3 tests/g1_handoff.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf ~/github/ESCape32/build-qemu-am13e/AM13E-rev17.3.elf \
  --xtal-present --timed-steps --startup-steps 32768
```

At shift=10, each guest instruction is charged 1024 virtual
nanoseconds, so 9.984ms nominally requires 9750 guest instructions
*after the XTAL enable request*. The increased 32768-step bound
allows observation beyond this deadline. This is deliberately
accelerated and **does not** model 200MHz CPU cycles. Results show control-flow
progress only. Use the G2g QTest clock_step cases for actual timer
boundary validation.

### RSP error reply classification

The RSP client now rejects only exact two-hex-digit remote error
packets (`E01`, `E2a`, etc.). The earlier `result.startswith("E")`
incorrectly rejected QEMU's valid `qqemu.sstepbits` response
`ENABLE=1,NOIRQ=2,NOTIMER=4`. A host-only regression
`tests/test_rsp.py` is run by `test.sh` before guest tests. This
change does not modify firmware, CPU or SYSCTL/XTAL behavior.

## G2h: Native SYSPLLCFG0/1 RMW (not PLL lock)

An extended QEMU timed GDB trace of the original ESCape32 ELF
passed the virtual XTAL GOOD loop; the next precise BusFault was
`BFAR=0x400B0120`, `stacked_PC=0x0000917a`.
This is `SYSCTL.SYSPLLCFG0` per TI AM13E230x TRM
SPRUJF2B §§3.14.2.16–17 and SDK `hw_sysctl.h`.

G2h models **only** `SYSPLLCFG0` and `SYSPLLCFG1` with
32-bit read/write RMW: `CFG0` offset 0x1120, modeled fields
SYSPLLREF, ENABLECLK0/1 and RDIVCLK0/1 (mask `0x0000ff31`);
`CFG1` offset 0x1124, PDIV and QDIV (mask `0x00007f03`).
The documented reset parts are `CFG0=0x00000030`
(ENABLECLK0=ENABLECLK1=1) and `CFG1=0x00002300` (QDIV=0x23).
Unknown reserved reset X bits are represented as zero in this
virtual profile, not claimed as actual silicon values. QDIV=0
and QDIV=127 are rejected, along with reserved-bit changes.
Config writes are rejected if SYSPLLEN is asserted.

Firmware's 25MHz / 2 × (31+1) / 2 = 200MHz configuration is
accepted as register state, **not** proof of PLL lock, runtime
clock frequency, or motor safety. `CLKSTATUS` is unchanged.
SYSPLLPARAM0/1 and factory calibration remain unimplemented;
the next blocked MMIO or factory access should be diagnosed
rather than substituting fictional calibration values.

## G2i: TI Factory ROM, explicit provenance-preserving fixture

The original Rel17 ELF now advances past SYSPLLCFG0/1 and suffers
a *precise BusFault* with `BFAR=0x60111028`,
`stacked_PC=0x000091b0`. That is the 8–16MHz SYSPLL factory
lookup `PLLSTARTUP0_8_16MHZ` in TRM SPRUJF2B §3.16.11 and
SDK `hw_factoryregion.h`; the companion word is at `0x6011102c`.
The original ELF copies the pair to SYSPLLPARAM0/1 as opaque values.

G2i maps the FACTORY aperture starting at `0x60111000`.
By default **every** read/write in this region is rejected with
`MEMTX_ERROR` and logged `G2_FACTORY_UNAVAILABLE`. The emulator
never manufactures TI calibration data from reset tables or
imaginary register values.

To provide a caller-owned 8-byte *little-endian* binary pair from
a known source, explicitly supply
`-machine am13e23019,xtal-present=on,factory-pll-file=/absolute/path/to/factory_pll_pair.bin`.
Only two aligned 32-bit reads are enabled at
`0x60111028`/`0x6011102c`. Writes and all other FACTORY offsets
stay unmodeled. Missing or non-exactly-eight-byte files fail QEMU
initialization, not silently pad or return zero.

**Provenance:** the values are device-programmed factory
lookup/calibration values. The SDK contains their *addresses*
and field masks, not an AM13E23019's actual silicon bytes.
The G2i QTest creates unmistakable synthetic transport sentinels
only inside its own temporary directory to test readback and ROM
read-only behavior; these are **not PLL tuning values** and must not
be reused for clock-lock or frequency qualification.

The GDB helper supports an optional `--factory-pll-file PATH`
to observe further original ELF execution when separately sourced
valid data exists. G2i does not implement SYSPLLPARAM0/1,
analog PLL behavior, or fabricate SYSPLLGOOD. Without source data,
the same BFAR is the correct fail-closed result.

## G2j: SYSPLLPARAM0/1, opaque calibration-word transport

The AM13E230x TRM SPRUJF2B §§3.14.2.18–19 identifies
SYSPLLPARAM0/1 at `SYSCTL_BASE+0x1128`/`+0x112c`.
Both contain writable factory-derived tuning parameters. Their
documented reset fields produce emulator snapshots `0x810a0000`
and `0x0f00010f`. Unknown reset fields marked X are represented
by zero **only as an emulator convention**.

G2j implements 32-bit read/write storage of the *complete* words,
including undefined R/W-X bits, because the unmodified firmware
copies opaque data from a separately provisioned FACTORY address.
No attempt is made to interpret or invent the per-chip values.
Both writes are blocked while SYSPLL is enabled, as described by
TRM `CLKSTATUS.SYSPLLBLKUPD` semantics. No automatic lock,
clock-frequency output, or GOOD bits are produced by parameter
writes.

The independent QTest `tests/g2_pllparam.py` provisions an
**explicit, temporary 8-byte synthetic transport fixture**, then
validates the actual FACTORY→SYSPLLPARAM full-word copy and
readback. The synthetic fixture is *not* TI analog calibration and
must never be used to qualify PLL frequency, lock or physical
motor-controller behavior.

The real ELF still stops at the first unprovisioned FACTORY read
by default. To trace beyond it, an independently sourced factory
pair must be passed via `--factory-pll-file`; all subsequent
behavior needs its own evidence. Physical SYSPLL model and
G2 Scheduler acceptance remain outstanding.

## ESC-SIM: software-control-first profile

With `-machine am13e23019,esc-sim=on` (or
`tests/g1_handoff.py --esc-sim --timed-steps`) the emulator
uses synthetic FACTORY PLL parameter defaults `0x810a0000`,
`0x0f00010f` and virtual XTAL/PLL startup timers. Those
defaults are **not** TI per-chip calibration; the 50µs virtual
PLL startup interval is a functional simulation constant, not
silicon timing. Only the firmware's valid 25MHz→200MHz
divider configuration and explicit SYSPLLEN request may start
the simulated PLL. SYSPLLGOOD and HSCLKGOOD then emerge after
virtual elapsed time, and the MCLK switch is accepted.

Default strict mode and earlier register tests remain unchanged.
The purpose is to unblock unchanged ESCape32 ELF startup so
the QEMU work can prioritize TIMG4/DMA2 DShot capture,
MCPWM4 phase PWM, TIMG12 delayed commutation, CMPSS0/ECAP1
BEMF edges, ADC0/1/2 sampling and an external BLDC plant.
The profile does NOT validate PLL trim, frequency, silicon clocks,
PCB safety, or high-current power-stage operation.

## G3a — GPIO Peripheral Power, Reset, Digital I/O

With ESC-SIM active the original ELF passes the virtual 25MHz
XTAL/SYSPLL/MCLK initialization and next faults on
`GPIO0_BASE(0x400F0000)+PWREN(0x800)=0x400F0800`
at `stacked_PC=0x00007640`. The stacked `R2=0x26000001`
is the TI `DL_GPIO_enablePower(GPIO0)` access, rather than
a motor-control arithmetic failure.

G3a adds four isolated GPIO banks (GPIO0..3, 0x2000 spacing)
using TI SDK `hw_memmap.h`, `hw_gpio.h`, and `dl_gpio.h`:
- `GPRCM.PWREN` at +0x800 requires write KEY 0x26, retaining
  ENABLE bit 0 and reading key as 0.
- `GPRCM.RSTCTL` at +0x804 requires write KEY 0xB1; RESETASSERT
  clears digital DOUT/DOE and sets STAT.RESETSTKY[16]. Sticky
  clear is available independently.
- GPIO DOUT/SET/CLR/TGL and DOE/SET/CLR aliases are backed
  by local digital port state after power-enable.
- DIN +0x1380 currently returns only the internally driven
  `DOUT & DOE` for basic software testing. **External input
  stimulus, analog pins, GPIO edge interrupts, and IOMUX
  peripheral routing are not yet implemented.** Do not treat
  this as a physically wired external pin state.
- Unknown GPIO MMIO addresses/widths and invalid GPRCM keys
  remain `MEMTX_ERROR` (no blanket fake register behavior).

`tests/g3_gpio.py` checks reset state, rejected keyless PWREN,
valid power-on/off, alias readback, reset sticky semantics and
per-port isolation. These are QTests, **not** evidence of DShot
input, PWM drive, motor spin or BEMF feedback. The next runtime
trace should identify the smallest additional IOMUX/Timer/ADC
MMIO surface needed for the unchanged ELF to initialize.

## G3b — IOMUX PINCM routing for nFAULT and future ESC signal paths

In ESC-SIM, the original ELF has passed G3a GPIO0 power-on and now
raises a precise BusFault at `BFAR=0x400CC058`,
`stacked_PC=0x00007660`, trying to write `0x00040081`.
Per TI `hw_memmap.h`, `hw_iomux.h` and AM13E
`board_io.h`, this is `IOMUX->PINCM[22]` for **PA22 nFAULT**:
`PF=1` (GPIO), `PC=1`, `INENA=1`.

G3b maps exactly 108 PINCM registers
`0x400CC000 + 4*i`, `i=0..107`, with 32-bit
read/write persistence of SDK-defined fields: PF, PC,
pull-up/down, input enable, hysteresis, drive strength,
Hi-Z, inversion and wakeup controls. Unspecified bits
and hardware-only WAKESTAT are not writable, and
indices 108+ remain rejected (`MEMTX_ERROR`).
Reset clears all PINCM words. Unlike a generic MMIO
catch-all this preserves per-pad ownership and software
readback checks.

G3b does **not** implement electrical signal level,
external nFAULT deassertion, PA26 DShot edges, MCPWM4
waveforms, or IRQ routing. These are separate functional
simulation components to add next. This pin-configuration
model is prerequisite, not motor SITL acceptance.

## G3c: ESC-SIM GPIO bootstrap as a single compatibility batch

The first BusFault after G3b was `GPIO0.CPU_INT.IMASK` at
`0x400F1028`, proving that the original firmware reached its
PA22 nFAULT IRQ configuration. Do not iterate one unrelated GPIO
register at a time.

In opt-in `esc-sim=on` only, all three documented GPIO interrupt
blocks (`CPU_INT`, `GEN_EVENT0`, `GEN_EVENT1`) support IMASK,
RIS, MIS, IIDX, ISET, and ICLR software-visible state; with no
external event source, RIS/MIS default to zero. This is register
semantics and software-set flags, not completed NVIC GPIO IRQ
delivery. All twelve SDK-defined ancillary GPIO configuration
registers (clock override, polarity, filtering, wake, DMA mask,
subscriber, etc.) have 32-bit shadow state. DIN/DOUT nibble aliases
are available as well. Unknown GPIO addresses are **not**
blanket-mapped; other motor-critical peripherals are untouched.

When PA22's PINCM is `GPIO + PC + INENA`, GPIO0.DIN bit22
is **HIGH by default (nFAULT deasserted)**. For a fixed initial
fault level, use `-machine ...,esc-sim=on,esc-sim-nfault-asserted=on`:
the digital input becomes LOW. This is an initial-level fixture,
not full edge detection or fault-trip event injection. PA26 DShot
does not receive a fictitious signal. GPIO power keys and
Strict Mode's default fail-closed policy are retained.

Next objective: reach the unchanged Rel17 core initialization,
then implement TIMG4/DMA capture and MCPWM/BEMF/ADC interfaces
rather than expanding low-value GPIO emulation further.

## G4a: ADC/TIMG peripheral GPRCM as one shared ESC-SIM bootstrap

The original ELF progressed through GPIO and IOMUX setup, then
performed `DL_ADC_reset(ADC0)` with `R0=0x40000000`,
`R3=0xb1000003`, faulting at `BFAR=0x40000804`.
TI SDK `hw_adc.h` and `hw_gptimer.h` define GPRCM
`PWREN(+0x800)`, `RSTCTL(+0x804)`, `STAT(+0x814)`
with the same unlock passwords for ADC0, ADC1, ADC2,
TIMG4 (DShot capture) and TIMG12 (commutation timer).

G4a provides **one shared setup model** for all five modules:
reset sticky, reset-sticky clear, password-checked power on/off,
reset/enable readback. This is enabled only by `esc-sim=on`;
strict runs keep returning `MEMTX_ERROR`. All other ADC/TIMG
offsets remain unassigned: **there are no fictitious ADC samples,
timer counters, capture/DMA edges, or timer interrupts**.

`tests/g4_peripheral_gprcm.py` tests all five modules,
invalid passwords, reset status/clear, independent power and the
fail-closed default. Next step should implement actual ESC
data/control paths, not more single-register GPRCM patches.

## G4b — Native ADC0/1/2 sequencer and deterministic sampling

The unchanged ELF now passed GPIO and GPRCM setup and faulted
at `ADC0.ADCCTL2 = 0x40001004` (stacked_PC 0x0000cf80).
Rather than register-by-register GPRCM extensions, G4b maps the
TI ADC0/1/2 `ADCCTL1/2`, SOC0..15, PPB1..4, Interrupt
Selection/Flag/Clear, and SEQCTL / SEQ1..4 CONFIG registers.
The configuration addresses are cross-checked with SDK
`hw_adc.h` and actual firmware
`analog_sampling_backend.c`.

ADC RESULT0..15 are separate memory-mapped, read-only
16-bit registers at `ADC0RESULT_BASE=0x4000A000`,
`ADC1RESULT_BASE=0x4000B000`,
`ADC2RESULT_BASE=0x4000C000`. Configuring ADC does
not generate samples or interrupt flags. After a valid
SEQ1 SWFRC trigger, a QEMU virtual timer delays completion
20µs (simulator-only fixed interval, NOT TI ADC timing).
Only then are results copied from the raw input-code table and
`ADCINTFLG` asserted, with ADC0/1/2 INT1 outputs connected to
NVIC IRQ8,13,18 as in `startup_gcc_arm.c`. Clearing
`ADCINTFLGCLR` deasserts the IRQ.

`-machine am13e23019,esc-sim=on,esc-sim-adc-fixture-file=/PATH`
accepts exactly **192 bytes** (`uint16_le[3][32]`),
each input code 0..4095. Omitting the fixture uses the
explicit synthetic 2048-code midpoint, not an actual current,
bus voltage or temperature. These are *static analog inputs*,
not yet a live virtual motor plant or analog transfer model.
No calibration/temperature/overcurrent claim is made. The
external Python motor plant must eventually drive these
channels dynamically; the ADC sequencer conversion interface
and NVIC timing remain guest-firmware-owned. Strict mode
retains its fail-closed ADC data-path behavior.

## G1 fast delay trace (full guest execution)

After G4b QTest passed, the unchanged Rel17.3 ELF reached
`0xC6F6/0xC6F8/0xC6FA`, the TI SDK `DL_Common_delayCycles`
`SUBS; NOP; BHS` loop. `analog_sampling_backend.c` requests
`mclk_hz/2000` delay cycles for ADC startup (500µs at 200MHz).
The earlier 32768-step GDB budget ended mid-delay, **not a HardFault**.

The opt-in diagnostic `--esc-sim --timed-steps --fast-delay-loops`
verifies the actual Thumb NOP/BHS encodings, sets temporary GDB
breakpoints at LR's return PC and HardFault vector, sends GDB
`continue`, and removes the breakpoints after stop. **QEMU still
executes all guest instructions and clock events.** Only the RSP
round trips of the known busy-loop are avoided. Unexpected opcodes,
timeouts, wrong stop PC, or unsupported breakpoints fail closed.
The hardcoded PC is specific to this exact ELF, not portable to
arbitrary rebuilt images.

With accelerated observation, trace `steps` counts host GDB
observations, **not all executed guest instructions**. The existing
`icount shift=10` is diagnostic virtual time only, not physical
Cortex-M33 cycle timing.

## G4c — SDK ADC interrupt clear Read-Modify-Write

After G4b passes, original ESCape32 Rel17.3 executes two
verified SDK delay loops and then HardFaults at
`stacked_PC=0x0000777a`, `BFAR=0x40001024`
(ADC0.ADCINTFLGCLR). TI AM13E SDK `dl_adc.h`
`DL_ADC_clearInterruptStatus` uses
`adc->ADCINTFLGCLR |= mask`, which first **reads** the
register. The G4b model handled a W1C **write** only.

G4c implements the missing ESC-SIM readable W1S/W1C strobe
interface for ADCINTFLGFRC, ADCINTFLGCLR, ADCINTOVFCLR,
ADCSOCOVFCLR1 and ADCEVTCLR across ADC0/1/2. Each read
returns the simulator's empty strobe latch (zero); pending
interrupt status remains visible only through ADCINTFLG,
and only writes change interrupt/overflow flags. The
SDK uses `|=` on all five of these strobe registers.
This readback is a functional simulation convention, not
a silicon readback assertion. Strict Mode is unchanged.

The existing `tests/g4_adc_sequencer.py` QTest now
verifies the read half of each RMW and tests actual
conversion → pending flag → RMW clear → force →
RMW clear for ADC0/1/2, without modifying ELF or
sensor sampling intervals.

## G5: WWDT0 input-loss Watchdog functional timing (ESC-SIM)

The unmodified Rel17.3 ELF advances beyond all ADC0/1/2 setup
and four TI SDK delay loops, then faults at
`BFAR=0x400D0800`, `PC=0x0000C222`:
`WWDT0.GPRCM.PWREN`. Unlike incidental peripheral setup,
the firmware's `mcu/AM13E/hal/input_watchdog.c` specifically
uses WWDT0 to detect absence of **valid DShot input**.
The program requires powered=true and running=false during
preparation. The watchdog arms only after selecting a receiver
and is fed only by valid command acceptance.

ESC-SIM adds WWDT0 as sixth participant in the existing keyed
GPRCM Power/Reset/STAT model, with an independent WWDTCTL0/1,
WWDTCNTRST and WWDTSTAT implementation. The 0xC9/0xBE keys
guard configuration; 0xA7 is a valid Feed. A virtual-time
timer uses nominal 32768Hz LFCLK and the selected
period/divider: the firmware's 2^15 / 32768 policy is 1s.
Power on alone never claims RUN=1. SYSCTL.SYSTEMCFG
(0x400B0180) with 0x1B write key supports the WWDT
reset/NMI policy selection.

**Safety limitations:** expiration logs `ESC_SIM_WWDT_EXPIRED`
and clears RUN; the simulator does **not yet implement**
physical BOOTRST, persistent reset cause, gate shutdown, or
analogue protection. No result here qualifies a production
DShot input-loss fail-safe. Those state/event connections
belong with the DShot capture and motor plant.

`tests/g5_wwdt.py` tests pre-arm state, power key, system
policy, CTL0 arm, virtual feed deadline, observable expiry,
sticky reset, and strict-mode rejection. Unsupported WWDT
registers remain rejected instead of silently enabled.

## G6: TIMG4/DShot timebase and TIMG12 commutation scheduling

After G5 WWDT0 setup, the unmodified ESCape32 ELF faults at
`BFAR=0x40181008`, `stacked_PC=0xD2EA`:
`TIMG4.CLKSEL` in TI `hw_gptimer.h`. This is the
**actual PA26 DShot RX timer**, not unrelated board I/O.
`command_reply.c` and `command_capture.c` select
BUSCLK/1, prescale 0 (100MHz expected) and share TIMG4
CCP0 with DMA0 channel2, while `motor_event_timer.c`
uses **separate TIMG12** as the commutation one-shot.

G6 maps each timer's TI native control/interrupt/counter
window (+0x1000..+0x18ff), without swallowing unknown
registers. CLKSEL, CLKDIV, CCLKCTL, CPS, LOAD,
CTR/CTRCTL, capture-compare configs, CPU_INT,
GEN_EVENT0/1 and ancillary documented fields use
separate per-timer state. BUSCLK=100MHz is an
**ESC-SIM functional assumption**, not proof of real
silicon clock calibration. Counter readings follow
QEMU virtual time, zero events occur at timer deadlines,
and masked CPU zero-interrupts reach ARM NVIC IRQ44
(TIMG4) / IRQ45 (TIMG12). STOP cancels the pending
event; one-shot stops after the zero, periodic re-arms.
GPRCM reset clears the timer's pending event and state.

**Critically not yet implemented:** PA26 input rising/falling
edge injection, CC0 latching from real pin events,
DMA0 Channel2 source-34 transfers to firmware SRAM,
TIMG4 bidirectional TX DMA, and MCPWM power-stage
waveforms. Merely programming capture configuration
will never create fabricated DShot frames or watchdog
feeds. Those are the next direct hardware-to-plant
interfaces, together with TIMG12 commutation tests
against the unchanged firmware ISR.

`tests/g6_timers.py` verifies SDK clock configuration,
TIMG4 periodic 16-bit rollover and no invented capture,
TIMG12 delayed one-shot zero interrupt/clear,
peripheral isolation, reset, and default strict
failure. This is timer/IRQ infrastructure, **not yet
a functional DShot or motor control SITL PASS**.

## G7 — DMA0 registers and real CH2 memory-beat transport

After G6 timer initialization the unchanged ESCape32 ELF faults
at `BFAR=0x40021220`, stacked PC `0x00008A86`.
TI `hw_dma.h` identifies this as **DMA0.DMACHAN[2].DMACTL**.
The original `command_capture.c` maps TIMG4 CCP0 capture
to DMA0 Channel 2, trigger source **34**. BiDShot reuses
the channel for reply output through GPIO DOUTTGL.

G7 maps all 12 DMA channel control/source/destination/remaining-
count and trigger-select registers, CPU_INT IIDX/IMASK/RIS/
MIS/ISET/ICLR, priority and ancillary settings. All are
software-readable. Channel 2 supports a real 32-bit single
transfer per **explicit** DMA request, copying through QEMU's
guest address space (not bypassing firmware SRAM), updating
DMASA, DMADA, DMASZ, setting early threshold and complete
interrupt flags, and driving NVIC IRQ40. An unsupported width/
address generates DMA address-error status instead of silently
succeeding.

**No fake captures:** simply enabling Channel 2 with external
trigger 34 does not move bytes, set flags or feed WWDT.
A PA26 pin-edge input injection → TIMG4 CCP0 event → DMA trigger
is the next G7b dependency. Until connected, this is genuine
DMA transport infrastructure and firmware init readback,
**not** DShot receive verification. Channel 0/1/3..11 are
configuration-only. Strict mode continues rejecting DMA MMIO.

`tests/g7_dma.py` checks all 12 configurations, external
trigger with no spontaneous capture, real four-word SRAM copying
on explicit software requests, address/count progression,
half-size/complete interrupt flags, error status and strict mode.

## G7b: explicit PA26 edge input → TIMG4 CC0 → DMA0 CH2 → guest SRAM

G7b introduces a **test-only, non-silicon address**
`0x5FFE0000` in `-machine am13e23019,esc-sim=on`.
Writing 32-bit `0` or `1` drives the external logical PA26
pin level. Reads at +0/+4/+8/+12 report current level,
accepted transitions, hardware captures and DMA beats. The
test address is **NOT a TI AM13E peripheral and must not be
accessed by production ESCape32 firmware**; it exists only as
a deterministic injection interface for simulator/test clients.
Strict Mode rejects it.

A level change becomes a hardware capture **only** when
GPIO0 is powered, PA26 is an input with
`IOMUX.PINCM[26]=0x00040083`
(PF3 TIMG4 CCP0 + PC + INENA), TIMG4 is
running at configured BUSCLK in UP mode, and CCCTL_01[0]
is CAPTURE with matching edge condition. The captured 16-bit
counter timestamp enters the actual TIMG4 CC_01[0] register
at `0x40181810`; software reads see the same value.

Only if TIMG4 GEN_EVENT1 has CCU0 enabled (bit8)
and DMA0 CH2 is **enabled** with external trigger34,
the existing G7 32-bit DMA transfer function reads that
physical timer register and writes one actual word to the
firmware-owned Guest SRAM destination. Source/destination
address, DMASZ, early/complete interrupt status and IRQ40
retain the same G7 semantics. The simulation does **not**
call ESCape32 decoder functions, inject a completed packet,
or feed WWDT.

`tests/g7b_pa26_capture.py` covers missing IOMUX,
missing GEN_EVENT1 mask, incorrect DMA trigger, 32-edge
DShot600 waveform, SRAM timestamp timing, checksum and
remaining length, no extra DMA transfers after completion,
and strict-mode rejection. These are **hardware-path
QTests, not yet proof the unmodified Firmware finished
initialization or decoded a frame**. The next acceptance
is to boot firmware until `initio()` is ready, then drive
identical pin-level events during guest execution and
observe its own decoder/WWDT/command-output state.

No GUI board, physical pin, motor load or analog conversion
is implied by this fixture.

## G8: SYSCTL motor-control power, reset and PWM sync batch

G7b peripheral QTests passed and the unchanged Rel17.3 ELF
advanced beyond PA26 capture/DMA configuration before
`BFAR=0x400B048C`, stacked PC `0x00009946`.
The TI SDK `hw_sysctl.h` identifies this as
`SYSCTL.SOCLOCK.PERCLKCR` at offset `0x148C`,
not a new DMA or TIMG fault. Bit 0 is `TBCLKSYNC`:
PWM time-base counters are gated by this register.

G8 adds opt-in ESC-SIM-only digital control state:
`PERCLKCR.TBCLKSYNC`, `PWREN_MCPERIPH` (+0x1424),
`RSTCTL_ASSERT_MCPERIPH` (+0x1428),
`RSTCTL_CLEAR_MCPERIPH` (+0x142C), and
`STAT_MCPERIPH` (+0x1430). These are the shared power and
reset controls for EQEP0..2, ECAP0/1, PWM0..4, CMPSS0..3,
and XBAR, with documented KEY=0x26 (power) and KEY=0xB1
(reset) and valid bits 0..14. Power readback excludes the
write-only key; reset assert is sticky until cleared,
and reset command registers read as zero.

G8 also preserves digital read/write state for exact SDK
`CMPHPMXSEL`, `CMPLPMXSEL`, `CMPHNMXSEL`,
`CMPLNMXSEL`, `CMPSSCTL`, `CMPSSDACBUFCONFIG`,
and `ANAREFCTL` configuration addresses. They are NOT
synthetic comparator outcomes, ECAP BEMF edges, PWM
waveforms, or verified trip protection. The future MCPWM4
time-base model must honor `TBCLKSYNC` and the PWM4 power
bit, while CMPSS0/ECAP1/XBAR event sources must be driven
by the motor plant. Unknown MMIO addresses and strict-mode
operations still reject transactions.

`tests/g8_sysctl_motor.py` checks TBCLKSYNC gating state,
invalid clock bits, SDK-compatible RMW power/key behavior,
independent PWM4/ECAP1/CMPSS0/XBAR bits, reset sticky/clear
and strict-mode rejection. The acceptance for **real PWM**
is still a separate guest-driven signal/commutation test.

## G9a: real guest MCPWM4 output observer, no fabricated duty

`MCPWM4_BASE=0x40014000` uses the TI SDK `hw_mcpwm.h`
register offsets for `TBCTL`, `TBPRD`, `TBPRDS`,
`TBCTR`, `PWM1..3 CMPA/B active+shadow`,
`PWM1..3 AQCTLA/B active+shadow`, `DBCTL`,
`DBFED/RED`, `GLDCTL`, `GLDOSHTCTL/STS`, and
`ETSEL/ETPERIOD/INTEN/INTFLAG/INTCLR/INTFRC`.
MCPWM4 PWM power (SYSCTL bit9) and
`PERCLKCR.TBCLKSYNC` must both be enabled. The native
100MHz time-base count advances under QEMU Virtual Time,
generating zero interrupts at real counter boundaries
(NVIC external IRQ28). Rel17 one-shot global-load
shadow transactions are committed only on such events,
not immediately upon software writes.

A read-only **non-silicon** ESC-SIM observer at
`0x5FFE1000` reports running/status (+0), running
(+4), period ticks (+8), current counter (+C),
six internal AQ/DB levels (+10), validity mask (+14),
and six **HIGH ticks per carrier** (+18..+2C).
Levels are calculated from the active firmware-written
AQ and Compare registers and supported independent
dead-band timing, not from a throttle command or an
assumed duty setting. Unsupported AQ action types and
DB topology return **invalid** instead of silently
fabricating plausible output.

The observer is INTERNAL MCPWM logic, not a guarantee
that PB13 gate polarity, six physical pad routes or
gate-driver electrical conditions have been satisfied.
Its duty values must not be interpreted as energized
motor phases until those separate board conditions
are checked. Without explicit compile-time electrical
board output definitions, original ESCape32 can
deliberately keep gate drive disabled; the simulator
must not bypass that firmware decision. Likewise,
no motor BEMF or ECAP crossing is asserted by this
observer alone. Actual closed-loop validation requires
the host motor plant and CMPSS0/ECAP1 link.

`tests/g9_mcpwm_observer.py` checks TBCLKSYNC gating,
native six-AQ duty measurement, one-shot global
shadow load at Counter ZERO, firmware IRQ clear and
strict-mode refusal. No Trip Protection claim.
