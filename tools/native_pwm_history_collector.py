#!/usr/bin/env python3
"""G13B3 SIM_ONLY original-Guest WFI incremental QEMU PWM event collector.

The QEMU ring contains only 128 *retained* internal-AQ/DB events. This
read-only collector attaches at the native Gate-return checkpoint and
subsequently copies ONLY new sequence numbers at each stopped original
WFI. A QEMU historical buffer having already wrapped before attachment
does NOT imply an in-scope gap; an event overwritten before our next
poll DOES. No physical MOSFET timing, motor stability or guest writes.

QEMU virtual nanoseconds and original ECAP ticks are deliberately kept
as separate timestamps. No interpolated clock alignment is invented.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from .native_pwm_history import (
    BASE, CAPACITY, WORDS, KIND, NativePWMHistoryRecord, _header
)

DEFAULT_MAX_RECORDED_EVENTS = 100_000


def _count(header, key):
    return header[key + "_lo"] | (header[key + "_hi"] << 32)


def _decode_record(sequence: int, words: list[int], zero_limit: int
                   ) -> NativePWMHistoryRecord:
    if (len(words) != WORDS or any(type(w) is not int or
                                   w < 0 or w > 0xffffffff for w in words)):
        raise ValueError("Malformed native QEMU history word block")
    lo, hi, kind, old, new, counter, zero, aux = words
    if (kind not in KIND or old & ~0x3f or new & ~0x3f or
            aux & ~0x1070f or zero > zero_limit):
        raise ValueError("Invalid QEMU historical PWM event fields")
    if kind == 1 and old == new:
        raise ValueError("Clocked AQ/DB EDGE without six-level transition")
    if kind == 2 and counter != 0:
        raise ValueError("Original PWM ZERO callback had nonzero counter")
    return NativePWMHistoryRecord(
        sequence=sequence, virtual_ns=lo | (hi << 32),
        kind=KIND[kind], old_mask=old, new_mask=new,
        pwm_counter=counter, native_zero_count=zero,
        raw_pb13=aux & 1, pb13_doe=bool(aux & 2),
        gpio_powered=bool(aux & 4),
        pb13_pinmux_valid=bool(aux & 8),
        raw_trip_ost_bits=(aux >> 9) & 3,
        internal_level_evaluator_valid=bool(aux & 0x10000),
    )


class NativeWfiPWMHistoryCollector:
    """Read-only causal Guest WFI checkpoints; never owns a Guest socket."""

    def __init__(self, *, max_recorded_events=DEFAULT_MAX_RECORDED_EVENTS):
        if (type(max_recorded_events) is not int or
                not 1 <= max_recorded_events <= 1_000_000):
            raise ValueError("Explicit bounded event memory capacity required")
        self.max_recorded_events = max_recorded_events
        self.attached = False
        self.halted = False
        self.attach_total = None
        self.attach_dropped = None
        self.attach_invalid = None
        self.attach_zero = None
        self.next_sequence = None
        self.last_virtual_ns = None
        self.last_mask = None
        self.last_native_zero = None
        self.last_wfi = 0
        self.last_ecap_ns = None
        self.events = []
        self.polls = []
        self.gaps = []
        self.errors = []
        self.invalid_since_attach = 0
        self.in_scope_missing_events = 0
        self.max_events_copied_at_wfi = 0

    def attach(self, read32: Callable[[int], int], *, checkpoint: str):
        if self.attached or self.halted or checkpoint != (
                "native_gate_return_before_sustained_motor"):
            raise ValueError("Collector must start at one native Gate return")
        before = _header(read32)
        if before != _header(read32):
            raise ValueError("QEMU event-ring header changed during Gate attach")
        self.attach_total = _count(before, "total")
        self.attach_dropped = _count(before, "dropped")
        self.attach_invalid = before["invalid_count"]
        self.attach_zero = before["zero_events"]
        self.next_sequence = self.attach_total
        self.last_virtual_ns = _count(before, "last_time")
        self.last_mask = before["current_mask"]
        self.last_native_zero = before["zero_events"]
        self.attached = True
        return self.document()["attach"]

    def attach_safe(self, read32, *, checkpoint: str):
        """Preserve failed original Guest attach as unqualified evidence."""
        try:
            return self.attach(read32, checkpoint=checkpoint)
        except Exception as exc:
            self.halted = True
            self.errors.append({
                "at_wfi": 0, "type": type(exc).__name__,
                "message": str(exc), "recorded_partial_history": True,
                "collection_halted": True,
            })
            return None

    def _on_wfi(self, read32, *, wfi: int, ecap_elapsed_ns: int):
        if not self.attached or self.halted:
            raise ValueError("G13B3 history collector not attached or halted")
        if (type(wfi) is not int or wfi != self.last_wfi + 1 or
                type(ecap_elapsed_ns) is not int or ecap_elapsed_ns < 0 or
                (self.last_ecap_ns is not None and
                 ecap_elapsed_ns <= self.last_ecap_ns)):
            raise ValueError("Native Guest WFI/ECAP checkpoints are not consecutive")
        before = _header(read32)
        total = _count(before, "total")
        retained = before["count"]
        oldest = total - retained
        if total < self.next_sequence:
            raise ValueError("QEMU historical PWM ring reset or counter regressed")
        if before["zero_events"] < self.last_native_zero:
            raise ValueError("Original PWM ZERO event counter regressed")
        if before["invalid_count"] < self.attach_invalid + self.invalid_since_attach:
            raise ValueError("QEMU historical model invalid counter regressed")
        first = max(self.next_sequence, oldest)
        missing = first - self.next_sequence
        if len(self.events) + total - first > self.max_recorded_events:
            raise ValueError("Host bounded history storage full; no silent event loss")
        new = []
        previous = self.events[-1] if self.events and missing == 0 else None
        for sequence in range(first, total):
            # MMIO slots are enumerated OLDEST RETAINED first by QEMU.
            index = sequence - oldest
            pos = BASE + 0x80 + index * WORDS * 4
            words = [read32(pos + k * 4) for k in range(WORDS)]
            record = _decode_record(sequence, words, before["zero_events"])
            if previous is not None:
                if (record.virtual_ns < previous["virtual_ns"] or
                        record.native_zero_count < previous["native_zero_count"] or
                        (previous["internal_level_evaluator_valid"] and
                         record.internal_level_evaluator_valid and
                         record.old_mask != previous["new_mask"])):
                    raise ValueError("QEMU chronological sequence/order/mask discontinuity")
            elif not missing and not self.events and sequence == self.attach_total:
                if (record.virtual_ns < self.last_virtual_ns or
                        record.native_zero_count < self.last_native_zero or
                        (record.internal_level_evaluator_valid and
                         record.old_mask != self.last_mask)):
                    raise ValueError("First post-attach QEMU edge contradicts Gate snapshot")
            payload = asdict(record)
            payload["observed_at_native_wfi"] = wfi
            payload["observed_wfi_ecap_elapsed_ns"] = ecap_elapsed_ns
            new.append(payload)
            previous = payload
        after = _header(read32)
        if before != after:
            raise ValueError("QEMU event ring mutated during WFI bounded read")
        if (new and new[-1]["virtual_ns"] != _count(before, "last_time")):
            raise ValueError("Latest QEMU event timestamp differs from live ring")
        if (new and before["status"] & 2 and
                new[-1]["new_mask"] != before["current_mask"]):
            raise ValueError("Last QEMU internal PWM mask does not match ring")
        # Commit only after the entire exact-sequence snapshot is checked.
        prev_invalid = self.attach_invalid + self.invalid_since_attach
        invalid_added = before["invalid_count"] - prev_invalid
        self.invalid_since_attach += invalid_added
        if missing:
            self.in_scope_missing_events += missing
            self.gaps.append({
                "at_wfi": wfi,
                "missing_from_sequence": self.next_sequence,
                "missing_to_sequence_exclusive": first,
                "missing_events": missing,
                "oldest_currently_retained_sequence": oldest,
                "reason": "UNREAD_QEMU_RING_EVENTS_OVERWRITTEN_BEFORE_WFI",
            })
        self.events.extend(new)
        self.max_events_copied_at_wfi = max(
            self.max_events_copied_at_wfi, len(new))
        self.polls.append({
            "wfi": wfi,
            "native_ecap_elapsed_ns": ecap_elapsed_ns,
            "new_events": len(new),
            "missing_since_previous_poll": missing,
            "sequence_next": total,
            "qemu_total_events": total,
            "qemu_cumulative_dropped": _count(before, "dropped"),
            "qemu_model_invalid_added": invalid_added,
            "latest_model_valid": bool(before["status"] & 2),
            "qemu_zero_events": before["zero_events"],
        })
        self.next_sequence = total
        self.last_wfi = wfi
        self.last_ecap_ns = ecap_elapsed_ns
        self.last_virtual_ns = _count(before, "last_time")
        self.last_mask = before["current_mask"]
        self.last_native_zero = before["zero_events"]
        return self.polls[-1]

    def poll(self, read32: Callable[[int], int], *,
             wfi: int, ecap_elapsed_ns: int):
        """Never let a sideband collection exception rewrite the motor gate.

        Errors stop further collection and are preserved in the partial
        native trace. No fabricated missing records or repaired sequence.
        """
        if self.halted:
            return None
        try:
            return self._on_wfi(
                read32, wfi=wfi, ecap_elapsed_ns=ecap_elapsed_ns)
        except (Exception,) as exc:
            self.halted = True
            self.errors.append({
                "at_wfi": wfi, "type": type(exc).__name__,
                "message": str(exc), "recorded_partial_history": True,
                "collection_halted": True,
            })
            return None

    def document(self):
        return {
            "scope": "ORIGINAL_GUEST_WFI_INCREMENTAL_QEMU_INTERNAL_PWM_HISTORY",
            "source": "ACTUAL_ORIGINAL_REL17_WFI_STOPS_READ_ONLY_QTEST",
            "collection_enabled": self.attached,
            "attach": ({
                "checkpoint": "native_gate_return_before_sustained_motor",
                "total_events_at_attach": self.attach_total,
                "pre_attach_ring_dropped": self.attach_dropped,
                "pre_attach_invalid_model_count": self.attach_invalid,
                "pre_attach_zero_events": self.attach_zero,
                "pre_attach_history_not_collected": bool(self.attach_total),
                "first_in_scope_sequence": self.attach_total,
            } if self.attached else None),
            "events": self.events,
            "wfi_polls": self.polls,
            "gaps": self.gaps,
            "collection_errors": self.errors,
            "observed_wfi_count": len(self.polls),
            "last_polled_wfi": self.last_wfi,
            "stored_events": len(self.events),
            "in_scope_missing_events": self.in_scope_missing_events,
            "qemu_invalid_model_events_since_attach": self.invalid_since_attach,
            "max_events_copied_at_one_wfi": self.max_events_copied_at_wfi,
            "collector_halted": self.halted,
            "complete_since_gate_return": (
                self.attached and not self.halted and bool(self.polls) and
                not self.gaps and not self.errors and
                self.invalid_since_attach == 0 and
                self.polls[-1]["latest_model_valid"]
            ),
            "complete_since_qemu_pwm_reset": False,
            "full_past_carrier_edges_reconstructed": False,
            "qemu_virtual_ns_and_guest_ecap_ns_aligned": False,
            "physical_mosfet_edges_qualified": False,
            "actual_gate_driver_deadtime_qualified": False,
            "current_continuous_motor_plant_input_qualified": False,
            "motor_stability_qualified": False,
            "original_native_strict_rotor_gate_executed_here": False,
        }
