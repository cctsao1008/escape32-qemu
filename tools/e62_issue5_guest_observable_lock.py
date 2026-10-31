#!/usr/bin/env python3
"""SIM_ONLY E62 #5 candidate: guest-observable BEMF reacquisition safety guard.

No rotor theta/omega inputs! This is a candidate *evidence* classifier, not
the original firmware and not an implemented restart. Until multiple
direction-consistent phase transitions have been established, fail closed:
HOLD_UNQUALIFIED. A single comparator edge cannot distinguish a geometric
flux zero from omega=0. Intended as a spec/host oracle for separate
candidate firmware work, not a QEMU injection or Original P1 waiver.
"""
from dataclasses import dataclass,field
from enum import Enum

class Decision(str,Enum):
    HOLD_UNQUALIFIED="HOLD_UNQUALIFIED"
    REJECT_INVALID="REJECT_INVALID"
    PROVISIONAL_SEQUENCE="PROVISIONAL_SEQUENCE"
    EVIDENCE_SUFFICIENT_FOR_HANDOFF_REVIEW="EVIDENCE_SUFFICIENT_FOR_HANDOFF_REVIEW"

@dataclass(frozen=True)
class Observation:
    capture_ns:int
    # Selected physical comparator phase; must derive from existing
    # six-step multiplexer state, never read hidden QEMU rotor truth.
    phase:int
    # PWM sector index 0..5 independently observed at output; no fabricated
    # sector advancement to create qualification evidence.
    sector:int
    # Count and timing of actual timer-backed PWM sector transitions
    sector_transition_ns:int
    comparator_level:int

@dataclass
class GuestObservableGuard:
    minimum_sectors:int=3
    minimum_capture_interval_ns:int=100_000
    maximum_capture_interval_ns:int=32_768_000
    events:list=field(default_factory=list)
    invalid:bool=False

    def offer(self, event:Observation)->Decision:
        if self.invalid:return Decision.REJECT_INVALID
        if (event.capture_ns<0 or not 0<=event.sector<=5 or
            not 0<=event.phase<=2 or event.comparator_level not in (0,1) or
            event.sector_transition_ns>event.capture_ns or
            event.sector_transition_ns<0):
            self.invalid=True
            return Decision.REJECT_INVALID
        if not self.events:
            self.events.append(event)
            return Decision.HOLD_UNQUALIFIED
        prev=self.events[-1]
        dt=event.capture_ns-prev.capture_ns
        # Reject non-monotonic / unreasonably short / stale capture.
        if not self.minimum_capture_interval_ns<=dt<=self.maximum_capture_interval_ns:
            self.invalid=True
            return Decision.REJECT_INVALID
        # Repeated capture from identical phase/sector cannot certify
        # electrical progression; it may be omega=0 alias.
        if event.sector==prev.sector or event.phase==prev.phase:
            self.events.append(event)
            return Decision.HOLD_UNQUALIFIED
        if (event.sector-prev.sector)%6 != 1:
            self.invalid=True
            return Decision.REJECT_INVALID
        if event.sector_transition_ns<=prev.sector_transition_ns:
            self.invalid=True
            return Decision.REJECT_INVALID
        # Distinct actual source-backed sectors and comparator phase progression
        # are only a necessary condition, not proof of mechanical direction.
        self.events.append(event)
        consecutive=1
        for a,b in zip(self.events[::-1],self.events[-2::-1]):
            if ((a.sector-b.sector)%6==1 and a.phase!=b.phase and
                a.sector_transition_ns>b.sector_transition_ns):
                consecutive+=1
            else:
                break
        if consecutive<self.minimum_sectors:
            return Decision.PROVISIONAL_SEQUENCE
        return Decision.EVIDENCE_SUFFICIENT_FOR_HANDOFF_REVIEW
