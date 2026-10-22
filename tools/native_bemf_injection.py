#!/usr/bin/env python3
"""G13B3E native plant BEMF into NON-SILICON QEMU analog port only.

Never write firmware SRAM, native PWM/Gate/Trip/CMPSS/ECAP registers or
fabricate comparator edges, timestamps, interrupts or commutation.
"""
from dataclasses import dataclass, asdict
from typing import Callable
from .native_pwm_qualification import observe_original_pwm
from .native_bemf_qualification import observe_original_bemf_route
from .native_runtime_timeline import NativePwmTimeline
from .virtual_bldc_feedback import AnalogFrontend, SIM_BEMF_INPUT


@dataclass(frozen=True)
class NativeBemfStimulus:
    sample_index: int
    native_ecap_ticks: int
    motor_elapsed_ns: int
    selected_code: int
    selected_phase: int
    active_dac_code: int
    bemf_phase_v: tuple[float, float, float]
    sample_words: tuple[int, int, int]
    changed_from_neutral: bool

    def to_dict(self):
        return asdict(self)


class NativeBemfInjector:
    def __init__(self, frontend: AnalogFrontend):
        self.frontend = frontend
        self.records: list[NativeBemfStimulus] = []

    def inject(self, timeline: NativePwmTimeline,
               read32: Callable[[int], int],
               write32: Callable[[int, int], None], *,
               selected_code: int, native_armed: bool) -> NativeBemfStimulus:
        if not timeline.frames:
            raise ValueError("No original native PWM and timestamp observation")
        frame = timeline.frames[-1]
        physical = observe_original_pwm(read32, gate_active_level=1)
        if (not physical.acceptable_for_plant or
                physical.period_ticks != frame.pwm_period_ticks or
                physical.six_high_ticks != frame.six_high_ticks):
            raise ValueError(
                "Native PWM Gate/Trip changed since physical timestamp; "
                "BEMF injection forbidden")
        arm = observe_original_bemf_route(
            read32, selected_code=selected_code, native_armed=native_armed)
        if not arm.channel_ready_for_voltage_samples or arm.selected_phase is None:
            raise ValueError("Original BEMF capture route not armed: " + arm.reason)
        sample = timeline.motor.sample(gate_enabled=True)
        if (frame.bemf_phase_v != sample.bemf_phase_v or
                frame.phase_currents_a != sample.phase_currents_a):
            raise ValueError("Motor sample and native time observation disagree")
        words = self.frontend.words(sample)
        if len(words) != 3 or any((w & ~0x10fff) or not (w & 0x10000)
                                  for w in words):
            raise ValueError("Malformed three-phase analog voltage samples")
        # All safety checks and analog overflow checks precede ANY write.
        for phase, word in enumerate(words):
            write32(SIM_BEMF_INPUT + 4 * phase, word)
        for phase, word in enumerate(words):
            if read32(SIM_BEMF_INPUT + 4 * phase) != word:
                raise AssertionError("QEMU BEMF stimulus MMIO readback mismatch")
        zero = self.frontend.code(0.0)
        record = NativeBemfStimulus(
            sample_index=frame.index,
            native_ecap_ticks=frame.native_ecap_ticks,
            motor_elapsed_ns=frame.elapsed_ns,
            selected_code=selected_code,
            selected_phase=arm.selected_phase,
            active_dac_code=arm.active_dac_code,
            bemf_phase_v=sample.bemf_phase_v,
            sample_words=words,
            changed_from_neutral=any((w & 0xfff) != zero for w in words))
        self.records.append(record)
        return record

    def require_samples(self, *, min_samples: int = 4):
        if (len(self.records) < min_samples or
                not any(r.changed_from_neutral for r in self.records) or
                not any(r.motor_elapsed_ns > 0 for r in self.records)):
            raise AssertionError(
                "Insufficient physically derived native BEMF voltage samples")
        return {
            "sample_count": len(self.records),
            "nonneutral_samples": sum(r.changed_from_neutral
                                      for r in self.records),
            "selected_phases": [r.selected_phase for r in self.records],
            "simulator_only_registers":
                [hex(SIM_BEMF_INPUT + 4 * i) for i in range(3)],
            "firmware_pwm_irq_cap_register_writes": False,
            "native_capture_proved": False,
            "native_closed_loop_proved": False
        }
