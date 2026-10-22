#!/usr/bin/env python3
"""Conservative necessary (not sufficient) cross-phase power path guard.

The older G13A reduced-order VirtualBLDC can rotate with one low-side-only
output because its voltage mapping pins the neutral artificially. For an
actual floating star motor that is NOT proof of applied DC bus energy.
This read-only criterion does not change or replace the old host model.
"""
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class PhysicalBridgePath:
    upper_phase_indices: tuple[int,...]
    lower_phase_indices: tuple[int,...]
    different_phase_pairs: tuple[tuple[int,int],...]
    qualifies_necessary_two_terminal_drive: bool
    reason: str
    def to_dict(self):
        return asdict(self)

def qualify_cross_phase_bridge(six_high_ticks, *, period_ticks:int,gate_trip_qualified:bool)->PhysicalBridgePath:
    if len(six_high_ticks)!=6 or period_ticks<=0 or any(not isinstance(x,int) or not 0<=x<=period_ticks for x in six_high_ticks):
        raise ValueError('Six measured physical PWM high counts required')
    uppers=tuple(i for i in range(3) if six_high_ticks[2*i]>0)
    lowers=tuple(i for i in range(3) if six_high_ticks[2*i+1]>0)
    pairs=tuple((hi,lo) for hi in uppers for lo in lowers if hi!=lo)
    reason=('GATE_TRIP_NOT_QUALIFIED' if not gate_trip_qualified else
            'NO_MEASURED_UPPER_MOSFET_SOURCE' if not uppers else
            'NO_MEASURED_LOWER_MOSFET_RETURN' if not lowers else
            'NO_DISTINCT_PHASE_SOURCE_TO_RETURN' if not pairs else
            'NECESSARY_CROSS_PHASE_PATH_PRESENT_NOT_SUFFICIENT_FOR_SUSTAINED_CLOSED_LOOP')
    return PhysicalBridgePath(uppers,lowers,pairs,bool(pairs and gate_trip_qualified),reason)
