#!/usr/bin/env python3
"""G13B3G TIMG12 read-only real hardware/IRQ image.

The QEMU backend implements AM13E230x TIMG12 at 0x40188000 +
the official +0x1000 clock/interrupt and +0x1800 counter windows.
No register writes, IRQ forcing, Guest SRAM mutations, or timer advance.
"""
from dataclasses import asdict, dataclass
from typing import Callable

TIMG12_BASE = 0x40188000


@dataclass(frozen=True)
class NativeTimg12Snapshot:
    native_ecap_ticks: int
    clksel: int
    clkdiv: int
    clock_enabled: int
    clock_prescaler: int
    irq_mask: int
    irq_raw: int
    irq_masked: int
    ctrctl: int
    period_load: int
    counter: int
    counter_enabled: bool
    counter_counts_up: bool
    remaining_ticks: int

    def to_dict(self):
        return asdict(self)


def observe_native_timg12(read32: Callable[[int], int], *,
                          native_ecap_ticks: int) -> NativeTimg12Snapshot:
    if not 0 <= native_ecap_ticks <= 0xffffffff:
        raise ValueError("Original ECAP1 counter must be 32-bit")
    def rd(offset):
        return read32(TIMG12_BASE + offset)
    clksel, clkdiv = rd(0x1008), rd(0x1000)
    clock_enable, cps = rd(0x1108), rd(0x110c)
    mask, raw, masked = rd(0x1028), rd(0x1030), rd(0x1038)
    ctl, load, count = rd(0x1804), rd(0x1808), rd(0x1800)
    enabled = bool(ctl & 1)
    count_up = bool(ctl & 0x20)
    if enabled and count_up and count > load:
        raise AssertionError("Original TIMG12 up-counter exceeds reload")
    remaining = (load + 1 - count if count_up
                 else count + 1) if enabled else 0
    return NativeTimg12Snapshot(
        native_ecap_ticks=native_ecap_ticks,
        clksel=clksel, clkdiv=clkdiv, clock_enabled=clock_enable,
        clock_prescaler=cps, irq_mask=mask, irq_raw=raw,
        irq_masked=masked, ctrctl=ctl, period_load=load,
        counter=count, counter_enabled=enabled,
        counter_counts_up=count_up, remaining_ticks=remaining)
