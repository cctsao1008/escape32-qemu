#!/usr/bin/env python3
"""Guest-owned SysTick clock for functional DShot scenarios.

Unlike ECAP1.TSCTR, the original ESCape32 16 kHz SysTick counter runs
before Gate/BEMF arming. No host sleeps or QEMU clock writes occur here.
A stopped guest tick does not advance scenario time and repeated stalls
fail closed; backwards or implausible forward jumps are not hidden.
"""

from __future__ import annotations


class OriginalGuestTickClock:
    TICK_NS = 62_500  # Pinned original Rel17 16 kHz SysTick.

    def __init__(self, original_tick: int, *, max_delta_ticks: int = 320,
                 max_stalled_observations: int = 64):
        if (type(original_tick) is not int or not 0 <= original_tick <= 0xffffffff
                or type(max_delta_ticks) is not int or not 0 < max_delta_ticks < 0x80000000
                or type(max_stalled_observations) is not int or max_stalled_observations < 1):
            raise ValueError('Invalid original guest SysTick clock configuration')
        self.origin_tick = original_tick
        self.previous_tick = original_tick
        self.max_delta_ticks = max_delta_ticks
        self.max_stalled_observations = max_stalled_observations
        self.elapsed_ns = 0
        self.stalled_observations = 0
        self.total_zero_delta_observations = 0
        self.last_delta_ticks = 0

    def observe(self, guest_tick: int) -> int:
        """Record a read-only Guest tick observation; return elapsed time ns."""
        if type(guest_tick) is not int or not 0 <= guest_tick <= 0xffffffff:
            raise ValueError('Invalid original Guest tick observation')
        delta = (guest_tick - self.previous_tick) & 0xffffffff
        if delta > self.max_delta_ticks:
            raise ValueError('Original Guest SysTick interval invalid/too large: '
                             +str(delta))
        if delta == 0:
            self.stalled_observations += 1
            self.total_zero_delta_observations += 1
            if self.stalled_observations > self.max_stalled_observations:
                raise ValueError('Original Guest SysTick did not advance after '
                                 +str(self.stalled_observations)+' WFI observations')
        else:
            self.stalled_observations = 0
            self.elapsed_ns += delta*self.TICK_NS
        self.previous_tick = guest_tick
        self.last_delta_ticks = delta
        return self.elapsed_ns
