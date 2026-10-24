#!/usr/bin/env python3
"""G13B3 edge *plan* from QEMU's ACTIVE AQ/DB evaluator (NOT actual edge log).

Read-only simulator sideband; it evaluates one hypothetical carrier with
today's active Guest MCPWM regs. No chronological switching history,
midcycle writes, measured output pins, external gate/diodes or real driver
dead-time is available. This MUST NOT feed a current-continuous plant.

The plan is cross-checked against the independent existing six-high-tick
QEMU observer, and all snapshot fields must remain unchanged during reads.
"""
from dataclasses import dataclass
from typing import Callable

from .native_pwm_qualification import observe_original_pwm

SWITCH_BASE = 0x5FFE6000
SWITCH_MAGIC = 0x50323645  # little-endian ASCII "E62P"
SWITCH_ABI = 1
MAX_EDGES = 64
STATUS_RUNNING = 1
STATUS_FULLY_VALID = 2
STATUS_OVERFLOW = 4
STATUS_MODEL_DERIVED = 8


@dataclass(frozen=True)
class CarrierModelEdge:
    tick: int
    mask_after: int


@dataclass(frozen=True)
class CarrierModelPlan:
    period_ticks: int
    model_timer_hz: int
    initial_mask: int
    last_mask: int
    edges: tuple[CarrierModelEdge, ...]
    six_high_ticks: tuple[int, ...]
    sampled_native_zero_count: int
    sampled_counter_tick: int
    snapshot_virtual_ns: int
    original_gate_and_trip_qualified: bool

    def to_dict(self):
        return {
            "scope": "QEMU_ACTIVE_AQ_DB_ONE_CARRIER_MODEL_RECONSTRUCTION",
            "source": "READ_ONLY_ESC_SIM_MCPWM4_ACTIVE_AQ_DB_EVALUATOR",
            "period_ticks": self.period_ticks,
            "model_timer_hz": self.model_timer_hz,
            "initial_mask": self.initial_mask,
            "last_mask": self.last_mask,
            "edges": [{"tick": e.tick, "mask_after": e.mask_after}
                      for e in self.edges],
            "six_high_ticks": list(self.six_high_ticks),
            "sampled_native_zero_count": self.sampled_native_zero_count,
            "sampled_counter_tick": self.sampled_counter_tick,
            "snapshot_virtual_ns": self.snapshot_virtual_ns,
            "cross_checked_with_existing_high_tick_observer": True,
            "original_gate_and_trip_qualified":
                self.original_gate_and_trip_qualified,
            "historical_chronological_edge_callbacks_observed": False,
            "midcarrier_register_changes_observed": False,
            "physical_gate_driver_deadtime_qualified": False,
            "external_mosfet_output_edges_measured": False,
            "physical_freewheel_topology_qualified": False,
            "current_continuous_plant_input_qualified": False,
            "native_closed_loop_motor_qualified": False,
        }


def _header(read32: Callable[[int], int]) -> dict:
    if read32(SWITCH_BASE) != SWITCH_MAGIC:
        raise ValueError("Native model-derived edge plan ABI magic missing")
    keys = (
        ("status", 4), ("period", 8), ("edge_count", 12),
        ("initial", 16), ("final", 20), ("hz", 24),
        ("counter", 28), ("zero_events", 32),
        ("virtual_lo", 36), ("virtual_hi", 40),
        ("abi", 44))
    result = {name: read32(SWITCH_BASE+offset)
              for name, offset in keys}
    if result["abi"] != SWITCH_ABI:
        raise ValueError("Unsupported QEMU switching-plan model ABI")
    return result


def reconstruct_high_ticks(*, period_ticks: int, initial_mask: int,
                           edges: tuple[CarrierModelEdge, ...]):
    """Dwell count at integer PWM ticks 0..period-1 (not pin-edge VCD)."""
    if not isinstance(period_ticks, int) or not 1 <= period_ticks <= 65536:
        raise ValueError("Unqualified carrier size")
    if not isinstance(initial_mask, int) or initial_mask & ~0x3f:
        raise ValueError("Invalid six-bit starting mask")
    counts = [0] * 6
    mask = initial_mask
    cursor = 0
    prior_tick = 0
    seen_wrap = False

    def dwell(n, level):
        if n < 0:
            raise ValueError("Edge chronology went backwards")
        for out in range(6):
            if level & (1 << out):
                counts[out] += n

    def no_shoot_through(level):
        if any((level & (3 << (2*i))) == (3 << (2*i))
               for i in range(3)):
            raise ValueError("Model plan contains simultaneous H/L on one leg")

    no_shoot_through(mask)
    for edge in edges:
        if not isinstance(edge, CarrierModelEdge):
            raise TypeError("CarrierModelEdge evidence required")
        if (not isinstance(edge.tick, int) or not isinstance(edge.mask_after, int)
                or not prior_tick < edge.tick <= period_ticks or
                edge.mask_after & ~0x3f):
            raise ValueError("Invalid edge tick/mask chronology")
        if edge.mask_after == mask:
            raise ValueError("Spurious no-op edge in QEMU model plan")
        dwell(edge.tick-cursor, mask)
        no_shoot_through(edge.mask_after)
        if edge.tick == period_ticks:
            if edge.mask_after != initial_mask:
                raise ValueError("Model carrier wrap does not return to initial mask")
            seen_wrap = True
        mask = edge.mask_after
        cursor = edge.tick
        prior_tick = edge.tick
    dwell(period_ticks-cursor, mask)
    if mask != initial_mask and (edges or not seen_wrap):
        raise ValueError("Missing period-wrap edge")
    if cursor < period_ticks:
        last_mask = mask
    else:
        last_mask = edges[-2].mask_after if len(edges) > 1 else initial_mask
    return tuple(counts), last_mask


def capture_qemu_carrier_plan(read32: Callable[[int], int]) -> CarrierModelPlan:
    """Only a paused, unchanging QEMU model snapshot can be admitted.

    No Host/Guest writes, no timer stepping, no feedback, no interpolation.
    Read-only existing output observer establishes duty equality.
    """
    before = _header(read32)
    st = before["status"]
    if ((st & (STATUS_RUNNING | STATUS_FULLY_VALID |
               STATUS_MODEL_DERIVED)) != (
                   STATUS_RUNNING | STATUS_FULLY_VALID |
                   STATUS_MODEL_DERIVED) or
            st & STATUS_OVERFLOW or st & ~0x0f):
        raise ValueError("Native QEMU edge plan not running/valid or overflowed")
    n = before["edge_count"]
    period = before["period"]
    if (not isinstance(n, int) or n > MAX_EDGES or
            not 1 <= period <= 65536 or
            before["hz"] <= 0 or before["counter"] >= period or
            before["initial"] & ~0x3f or
            before["final"] & ~0x3f):
        raise ValueError("Invalid QEMU edge-plan header")
    edges = tuple(CarrierModelEdge(read32(SWITCH_BASE+0x40+8*i),
                                    read32(SWITCH_BASE+0x44+8*i))
                  for i in range(n))
    existing = observe_original_pwm(read32)
    after = _header(read32)
    if before != after:
        raise ValueError("QEMU PWM plan source changed while reading snapshot")
    if not existing.native_pwm_valid or existing.period_ticks != period:
        raise ValueError("Original QEMU six-high output observer not valid")
    counts, computed_final = reconstruct_high_ticks(
        period_ticks=period, initial_mask=before["initial"], edges=edges)
    if counts != existing.six_high_ticks:
        raise ValueError(
            "Model edge plan HIGH-ticks disagree with original six outputs: " +
            repr({"carrier": counts, "observer": existing.six_high_ticks}))
    if computed_final != before["final"]:
        raise ValueError("Modeled final-level mask inconsistent")
    return CarrierModelPlan(
        period_ticks=period, model_timer_hz=before["hz"],
        initial_mask=before["initial"], last_mask=before["final"],
        edges=edges, six_high_ticks=counts,
        sampled_native_zero_count=before["zero_events"],
        sampled_counter_tick=before["counter"],
        snapshot_virtual_ns=(
            before["virtual_lo"] | before["virtual_hi"] << 32),
        original_gate_and_trip_qualified=existing.acceptable_for_plant)
