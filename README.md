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
