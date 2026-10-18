# escape32-qemu

Minimal AM13E23019 memory-only QEMU machine for ESCape32.

QEMU submodule: v6.2.0 (44f28df247). G0 maps Cortex-M33,
512 KiB Flash, 128 KiB SRAM and a shared SRAM Bank 3 code alias
(0x00C18000 = 0x20018000).

## WSL / Ubuntu

Install prerequisites:

    sudo apt install build-essential pkg-config libglib2.0-dev libpixman-1-dev libfdt-dev ninja-build meson python3

Build and verify against the original Rel17.3 ELF:

    git submodule update --init qemu
    ./build.sh
    ./test.sh ~/github/ESCape32/build-qemu-am13e/AM13E-rev17.3.elf

Build occurs in ignored .build/qemu-src, a separate QEMU git worktree.
The pinned qemu/ submodule is kept unchanged.

G0 test checks ELF vectors and SRAM alias bidirectionally using QTest.
**No guest instructions execute at G0**. The AM13E SYSCTL/FRI,
TrustZone-disabled CPU configuration, application boot handoff, motor
peripherals and power-stage behavior are not implemented yet.

References: TI AM13E230x TRM / SDK / ti-openocd;
ESCape32 am13e-port-v2, commit 0f21de6.
