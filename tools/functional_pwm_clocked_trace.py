"""Opt-in read-only QEMU MCPWM4 callback journal for E62 functional SITL.

Unlike WFI six-pad high-tick snapshots, events are QEMU virtual clock
callback/MMIO records. Neither timebase nor levels represent real MOSFET
pins. Read on *every* original running-loop WFI or fail closed on ring loss.

Does not align global QEMU virtual ns with Guest SysTick-relative ns.
No guest register writes, no synthetic histories or repaired edges.
"""
from __future__ import annotations

from tools.native_pwm_history import BASE, WORDS, CAPACITY, _header
from tools.native_pwm_history_collector import _decode_record


class FunctionalClockedPWMTrace:
    def __init__(self, *, max_events=100_000):
        if type(max_events) is not int or not 128 <= max_events <= 1_000_000:
            raise ValueError("Invalid bounded QEMU clocked history event limit")
        self.max_events = max_events
        self.attached = False
        self.stopped = False
        self.error = None
        self.events = []
        self.wfi_polls = []
        self.gaps = []
        self.attach_total = 0
        self.attach_dropped = 0
        self.attach_invalid = 0
        self.next_sequence = 0
        self.last_virtual_ns = 0
        self.last_mask = 0
        self.last_zero = 0
        self.last_wfi = 0
        self.last_guest_elapsed_ns = None
        self.invalid_delta = 0
        self.clocked_edges = 0
        self.zero_callbacks = 0
        self.unsafe_internal_masks = 0
        self.max_burst = 0

    @staticmethod
    def _read_stable_header(read32):
        first = _header(read32)
        if first != _header(read32):
            raise ValueError("QEMU PWM history header unstable")
        return first

    @staticmethod
    def _total(h):
        return h["total_lo"] | (h["total_hi"] << 32)

    @staticmethod
    def _dropped(h):
        return h["dropped_lo"] | (h["dropped_hi"] << 32)

    @staticmethod
    def _timestamp(h):
        return h["last_time_lo"] | (h["last_time_hi"] << 32)

    def attach(self, read32):
        if self.attached or self.stopped:
            raise ValueError("QEMU clocked functional history already attached")
        h = self._read_stable_header(read32)
        self.attach_total = self._total(h)
        self.attach_dropped = self._dropped(h)
        self.attach_invalid = h["invalid_count"]
        self.next_sequence = self.attach_total
        self.last_virtual_ns = self._timestamp(h)
        self.last_mask = h["current_mask"]
        self.last_zero = h["zero_events"]
        self.attached = True

    def poll(self, read32, *, wfi: int, guest_elapsed_ns: int,
             guest_step: int, guest_serviced: int):
        """Read only, preserve errors without converting them into passes."""
        if self.stopped:
            return
        try:
            self._poll(read32, wfi=wfi, guest_elapsed_ns=guest_elapsed_ns,
                       guest_step=guest_step, guest_serviced=guest_serviced)
        except Exception as exc:
            self.error = {"type": type(exc).__name__, "message": str(exc),
                          "at_running_wfi": wfi}
            self.stopped = True

    def _poll(self, read32, *, wfi, guest_elapsed_ns,
              guest_step, guest_serviced):
        if (not self.attached or type(wfi) is not int or
                wfi != self.last_wfi + 1 or
                type(guest_elapsed_ns) is not int or
                guest_elapsed_ns < 0 or
                (self.last_guest_elapsed_ns is not None and
                 guest_elapsed_ns < self.last_guest_elapsed_ns) or
                type(guest_step) is not int or
                not 0 <= guest_step <= 6 or
                type(guest_serviced) is not int or guest_serviced < 0):
            raise ValueError("Nonconsecutive original Guest WFI/clock/step snapshot")
        h = _header(read32)
        total = self._total(h)
        count = h["count"]
        oldest = total-count
        if (total < self.next_sequence or
                h["zero_events"] < self.last_zero or
                h["invalid_count"] < self.attach_invalid+self.invalid_delta):
            raise ValueError("QEMU PWM history counters regressed")
        start = max(self.next_sequence, oldest)
        missing = start-self.next_sequence
        if len(self.events) + total-start > self.max_events:
            raise ValueError("Bounded PWM history storage full, never truncate")
        batch = []
        last_ns = self.events[-1]["virtual_ns"] if self.events else self.last_virtual_ns
        last_mask = self.events[-1]["new_mask"] if self.events else self.last_mask
        last_zero = (self.events[-1]["native_zero_count"]
                     if self.events else self.last_zero)
        for sequence in range(start,total):
            index=sequence-oldest
            base=BASE+0x80+index*WORDS*4
            words=[read32(base+j*4) for j in range(WORDS)]
            r=_decode_record(sequence,words,h["zero_events"]).to_dict()
            if (r["virtual_ns"] < last_ns or
                    r["native_zero_count"] < last_zero or
                    (not missing and r["internal_level_evaluator_valid"] and
                     r["old_mask"] != last_mask)):
                raise ValueError("QEMU clocked PWM event chronology/mask discontinuity")
            r["observed_at_guest_wfi"]=wfi
            r["observed_guest_elapsed_ns"]=guest_elapsed_ns
            r["observed_guest_step"]=guest_step
            r["observed_guest_timg12_serviced"]=guest_serviced
            batch.append(r)
            last_ns=r["virtual_ns"]
            last_zero=r["native_zero_count"]
            last_mask=r["new_mask"]
        if h != _header(read32):
            raise ValueError("QEMU PWM history mutated during stopped Guest WFI")
        if batch and (batch[-1]["virtual_ns"] != self._timestamp(h) or
                      batch[-1]["new_mask"] != h["current_mask"]):
            raise ValueError("QEMU PWM event tail differs from current history header")
        if missing:
            self.gaps.append({"at_running_wfi":wfi,"missing_event_count":missing,
                              "missing_sequence_start":self.next_sequence,
                              "first_retained_sequence":start})
        self.events.extend(batch)
        self.max_burst=max(self.max_burst,len(batch))
        for r in batch:
            if r["kind"] == "QEMU_CLOCKED_AQ_DB_EDGE":
                self.clocked_edges += 1
            if r["kind"] == "QEMU_ORIGINAL_PWM_ZERO_CALLBACK":
                self.zero_callbacks += 1
            if r["internal_level_evaluator_valid"] and any(
                    (r["new_mask"] >> (2*ph)) & 3 == 3
                    for ph in range(3)):
                self.unsafe_internal_masks += 1
        self.invalid_delta=h["invalid_count"]-self.attach_invalid
        self.next_sequence=total
        self.last_virtual_ns=self._timestamp(h)
        self.last_mask=h["current_mask"]
        self.last_zero=h["zero_events"]
        self.last_wfi=wfi
        self.last_guest_elapsed_ns=guest_elapsed_ns
        self.wfi_polls.append({"wfi":wfi,"guest_elapsed_ns":guest_elapsed_ns,
                               "guest_step":guest_step,
                               "guest_timg12_serviced":guest_serviced,
                               "new_qemu_pwm_events":len(batch),
                               "missing_events":missing,
                               "qemu_pwm_total_events":total})

    def report(self, *, include_events=True):
        qualified=(self.attached and not self.stopped and
                   bool(self.wfi_polls) and not self.gaps and
                   self.invalid_delta == 0 and
                   self.clocked_edges > 0 and self.zero_callbacks > 0 and
                   self.unsafe_internal_masks == 0)
        r={
            "scope":"ORIGINAL_GUEST_RUNNING_WFI_INCREMENTAL_QEMU_CLOCKED_PWM",
            "source":"QEMU_EXECUTED_VIRTUAL_TIMER_AND_GUEST_MMIO_CALLBACKS",
            "status":("PASS_QEMU_CLOCKED_INTERNAL_PWM_HISTORY_ONLY"
                      if qualified else "OPEN_OR_FAIL_QEMU_CLOCKED_PWM_HISTORY"),
            "running_wfi_history_attach":self.attached,
            "total_history_events_at_attach":self.attach_total,
            "pre_attach_ring_dropped":self.attach_dropped,
            "history_since_attach_only":True,
            "full_pre_attach_history_qualified":False,
            "original_guest_systick_vs_qemu_global_ns_aligned":False,
            "exact_qemu_callback_virtual_ns_recorded":True,
            "physical_mosfet_edges_qualified":False,
            "physical_gate_deadtime_qualified":False,
            "original_firmware_or_guest_registers_modified":False,
            "collected_wfi":len(self.wfi_polls),
            "collected_events":len(self.events),
            "qemu_clocked_edge_callbacks":self.clocked_edges,
            "original_pwm_zero_callbacks":self.zero_callbacks,
            "unsafe_internal_both_gates_high_masks":self.unsafe_internal_masks,
            "qemu_pwm_invalid_model_events_since_attach":self.invalid_delta,
            "missed_ring_events":sum(g["missing_event_count"] for g in self.gaps),
            "gaps":self.gaps,
            "collection_error":self.error,
            "collector_halted":self.stopped,
            "max_events_between_guest_wfi":self.max_burst,
            "first_events":self.events[:8],
            "last_events":self.events[-8:],
        }
        if include_events:
            r["events"]=self.events
            r["wfi_polls"]=self.wfi_polls
        return r
