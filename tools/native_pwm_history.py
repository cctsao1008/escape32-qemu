#!/usr/bin/env python3
"""G13B3 QEMU-clocked MCPWM4 internal history, read-only SIM_ONLY.

Unlike the ACTIVE-register one-carrier plan at 0x5ffe6000, each
historical EDGE record is emitted only when the separate QEMU virtual
edge timer ACTUALLY fires, and ZERO at the original PWM ZERO callback.
REG/TRIP/GATE records reflect actual execution of corresponding QEMU
MMIO/state changes. This is QEMU internal logic, NOT physical MOSFET
gate-voltage measurements, switching transient/freewheel modeling, or
complete evidence across ring truncation.
"""
from dataclasses import dataclass
from typing import Callable

BASE = 0x5FFE7000
MAGIC = 0x48323645  # E62H
ABI = 1
CAPACITY = 128
WORDS = 8
HEAD_WORDS = (
    ("magic",0x00), ("status",0x04),("abi",0x08),("capacity",0x0c),
    ("count",0x10),("total_lo",0x14),("total_hi",0x18),
    ("dropped_lo",0x1c),("dropped_hi",0x20),
    ("current_mask",0x24),("zero_events",0x28),("counter",0x2c),
    ("last_time_lo",0x30),("last_time_hi",0x34),
    ("timer_hz",0x38),("event_words",0x3c),("invalid_count",0x40),
)
KIND = {
    1:"QEMU_CLOCKED_AQ_DB_EDGE",
    2:"QEMU_ORIGINAL_PWM_ZERO_CALLBACK",
    3:"QEMU_SHADOW_ACTIVE_LOAD",
    4:"QEMU_CLOCK_START_STOP",
    5:"QEMU_PWM_ACTIVE_MMIO_WRITE",
    6:"QEMU_TRIP_STATE",
    7:"QEMU_RAW_PB13_GPIO_PINCM_BOUNDARY",
    8:"QEMU_UNSUPPORTED_AQ_DB_OR_CLOCK_GAP",
}


@dataclass(frozen=True)
class NativePWMHistoryRecord:
    sequence: int
    virtual_ns: int
    kind: str
    old_mask: int
    new_mask: int
    pwm_counter: int
    native_zero_count: int
    raw_pb13: int
    pb13_doe: bool
    gpio_powered: bool
    pb13_pinmux_valid: bool
    raw_trip_ost_bits: int
    internal_level_evaluator_valid: bool

    def to_dict(self):
        return dict(vars(self))


@dataclass(frozen=True)
class NativePWMHistory:
    observed_events: tuple[NativePWMHistoryRecord,...]
    total_events_since_pmw_reset: int
    dropped_events: int
    invalid_model_samples: int
    last_virtual_ns: int
    sampled_native_zero_count: int
    current_internal_sixbit_mask: int
    qemu_pwm_clock_running: bool
    latest_internal_model_valid: bool
    model_timer_hz: int

    def to_dict(self):
        return {
            "scope":"QEMU_CLOCKED_INTERNAL_MCPWM_AQ_DB_HISTORY_SIM_ONLY",
            "source":"EXECUTED_QEMU_VIRTUAL_TIMER_AND_MMIO_CALLBACKS",
            "events":[r.to_dict() for r in self.observed_events],
            "retained_event_count":len(self.observed_events),
            "total_events_since_pwm_reset":self.total_events_since_pmw_reset,
            "dropped_events":self.dropped_events,
            "invalid_model_samples":self.invalid_model_samples,
            "latest_internal_model_valid":self.latest_internal_model_valid,
            "qemu_pwm_clock_running":self.qemu_pwm_clock_running,
            "last_virtual_ns":self.last_virtual_ns,
            "sampled_native_zero_count":self.sampled_native_zero_count,
            "current_internal_sixbit_mask":self.current_internal_sixbit_mask,
            "model_timer_hz":self.model_timer_hz,
            "chronological_qemu_callbacks_recorded":True,
            "complete_history_qualified":(
                self.total_events_since_pmw_reset > 0 and
                self.latest_internal_model_valid and
                self.dropped_events == 0 and
                self.invalid_model_samples == 0),
            "historical_physical_mosfet_edges_qualified":False,
            "gate_driver_deadtime_measured":False,
            "real_power_stage_freewheel_measured":False,
            "external_pin_waveform_measured":False,
            "current_continuous_plant_input_qualified":False,
            "strict_native_rotor_gate_qualified_by_this_trace":False,
        }


def _header(read32:Callable[[int],int]) -> dict:
    data={k:read32(BASE+off) for k,off in HEAD_WORDS}
    if data["magic"]!=MAGIC or data["abi"]!=ABI:
        raise ValueError("QEMU MCPWM historical ABI invalid or unmapped")
    if (data["capacity"]!=CAPACITY or data["event_words"]!=WORDS or
            data["status"] & ~0x0f or not data["status"] & 0x08 or
            data["count"]>CAPACITY or data["current_mask"] & ~0x3f or
            data["timer_hz"]<=0):
        raise ValueError("Unsupported historical QEMU ring status")
    total=data["total_lo"] | data["total_hi"]<<32
    lost=data["dropped_lo"] | data["dropped_hi"]<<32
    if (data["count"]!=min(total,CAPACITY) or
            lost!=max(0,total-CAPACITY) or
            bool(data["status"] & 4)!=bool(lost)):
        raise ValueError("Inconsistent bounded historical QEMU event counts")
    return data


def read_native_pwm_history(read32:Callable[[int],int]) -> NativePWMHistory:
    """At a QTest/paused native checkpoint. Never steps the PWM timer."""
    before=_header(read32)
    total=before["total_lo"] | before["total_hi"]<<32
    count=before["count"]
    records=[]
    for i in range(count):
        words=[read32(BASE+0x80+(i*WORDS+j)*4) for j in range(WORDS)]
        lo,hi,kind,old,new,counter,zero,aux=words
        if (kind not in KIND or old & ~0x3f or new & ~0x3f or
                aux & ~0x1070f or zero>before["zero_events"]):
            raise ValueError("Malformed QEMU clocked history event")
        r=NativePWMHistoryRecord(
            sequence=total-count+i,
            virtual_ns=lo | hi<<32,
            kind=KIND[kind],old_mask=old,new_mask=new,
            pwm_counter=counter,
            native_zero_count=zero,
            raw_pb13=aux & 1,
            pb13_doe=bool(aux & 2),
            gpio_powered=bool(aux & 4),
            pb13_pinmux_valid=bool(aux & 8),
            raw_trip_ost_bits=(aux>>9)&3,
            internal_level_evaluator_valid=bool(aux&0x10000),
        )
        if records:
            prior=records[-1]
            if (r.virtual_ns<prior.virtual_ns or
                    r.native_zero_count<prior.native_zero_count or
                    (prior.new_mask!=r.old_mask and
                     prior.internal_level_evaluator_valid and
                     r.internal_level_evaluator_valid)):
                raise ValueError("Historical QEMU event ordering/mask continuity invalid")
        if kind==1 and new==old:
            raise ValueError("QEMU clocked edge did not change any internal level")
        if kind==2 and counter!=0:
            raise ValueError("PWM ZERO callback did not show counter zero")
        records.append(r)
    after=_header(read32)
    if before!=after:
        raise ValueError("QEMU historical ring changed while reading")
    last=before["last_time_lo"] | before["last_time_hi"]<<32
    if records and records[-1].virtual_ns!=last:
        raise ValueError("Last historical event timestamp not retained")
    return NativePWMHistory(
        observed_events=tuple(records),
        total_events_since_pmw_reset=total,
        dropped_events=before["dropped_lo"] | before["dropped_hi"]<<32,
        invalid_model_samples=before["invalid_count"],
        last_virtual_ns=last,
        sampled_native_zero_count=before["zero_events"],
        current_internal_sixbit_mask=before["current_mask"],
        qemu_pwm_clock_running=bool(before["status"]&1),
        latest_internal_model_valid=bool(before["status"]&2),
        model_timer_hz=before["timer_hz"])
