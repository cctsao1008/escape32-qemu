"""Opt-in ORIGINAL-QEMU-clocked PWM -> current-continuous BLDC -> BEMF.

Only actual QEMU AQ/DB EDGE / ZERO / REG / TRIP / PB13 events are
accepted; the one-carrier prediction and 200-ms averaged PWM duty are
FORBIDDEN as motor switching inputs. Missing ring events fail CLOSED.
No original Guest SRAM/IRQ/PWM register writes are made.

This is a modeled original-Guest coupled experiment. It requires an
explicit Vbus/Ke/Kt/load profile and does NOT calibrate any E62 motor.
"""
from __future__ import annotations

from math import ceil
from .current_continuous_bldc import CurrentContinuousBLDC, LegTopology
from .native_motor_model_profiles import native_motor_parameters
from .virtual_bldc_feedback import AnalogFrontend, SIM_BEMF_INPUT
from .native_pwm_switching_plan import SWITCH_BASE


def _topology(mask: int, *, enabled: bool) -> LegTopology:
    if type(mask) is not int or mask & ~0x3f:
        raise ValueError("Invalid actual six-bit PWM level")
    if not enabled:
        return LegTopology(("Z", "Z", "Z"))
    phases = []
    for index in range(3):
        high = bool(mask & (1 << (2 * index)))
        low = bool(mask & (1 << (2 * index + 1)))
        if high and low:
            raise ValueError("Original PWM clocked history shows shoot-through")
        phases.append("H" if high else "L" if low else "Z")
    return LegTopology(tuple(phases))


def _raw_gate_enabled(record: dict) -> bool:
    return (record["raw_pb13"] == 1 and
            record["pb13_doe"] is True and
            record["gpio_powered"] is True and
            record["pb13_pinmux_valid"] is True and
            record["raw_trip_ost_bits"] == 0 and
            record["internal_level_evaluator_valid"] is True)


class NativeClockedCurrentCoupler:
    """Consume chronological executed QEMU PWM events, not averaged plan."""

    def __init__(self, *, initial_electrical_deg=-30.0,
                 motor_profile="reciprocal",
                 max_substep_ns=1000, max_wfi_gap_ns=2_000_000):
        if not (type(max_substep_ns) is int and
                1 <= max_substep_ns <= 20000 and
                type(max_wfi_gap_ns) is int and
                max_substep_ns <= max_wfi_gap_ns <= 10_000_000):
            raise ValueError("Explicit bounded current-continuous substeps")
        import math
        self.motor = CurrentContinuousBLDC(
            native_motor_parameters(motor_profile),
            initial_electrical_rad=math.radians(initial_electrical_deg))
        self.motor_profile = motor_profile
        self.frontend = AnalogFrontend(
            reference_v=3.3, zero_bemf_bias_v=1.65,
            input_gain_v_per_bemf_v=0.02)
        self.max_substep_ns = max_substep_ns
        self.max_wfi_gap_ns = max_wfi_gap_ns
        self.last_time_ns = None
        self.next_sequence = None
        self.last_mask = None
        self.records_consumed = 0
        self.analog_samples = 0
        self.total_integrated_ns = 0
        self.event_topology_changes = 0
        self.last_injected_voltage_words = None
        self.last_sample = self.motor.sample(gate_enabled=False)
        self.source = (
            "EXECUTED_ORIGINAL_GUEST_QEMU_CLOCKED_PWM_HISTORY_NOT_DUTY_PLAN")

    def attach(self, history, *, virtual_ns: int, gate_qualified: bool):
        if not history.attached or history.halted or (
                history.attach_total is None or
                type(virtual_ns) is not int or virtual_ns < 0 or
                type(gate_qualified) is not bool):
            raise ValueError("Require Guest Gate-return history attach")
        self.next_sequence = history.attach_total
        self.last_time_ns = virtual_ns
        self.last_mask = history.last_mask
        self.motor.set_switches(
            _topology(history.last_mask, enabled=gate_qualified))
        return self.evidence()

    def _advance(self, end_ns: int):
        if self.last_time_ns is None or end_ns < self.last_time_ns:
            raise ValueError("Motor integration would go backwards in QEMU time")
        elapsed = end_ns - self.last_time_ns
        if elapsed > self.max_wfi_gap_ns:
            raise ValueError("Unbounded unobserved Guest PWM switching gap")
        if elapsed:
            count = ceil(elapsed / self.max_substep_ns)
            step, extra = divmod(elapsed, count)
            for idx in range(count):
                ns = step + (idx < extra)
                self.last_sample = self.motor.advance(ns * 1e-9)
            self.total_integrated_ns += elapsed
        self.last_time_ns = end_ns

    def consume(self, history, *, guest_wfi: int, observed_virtual_ns: int):
        if self.last_time_ns is None or history.halted or history.gaps or (
                history.errors or history.invalid_since_attach or
                not history.attached):
            raise ValueError("Missing/invalid original Guest PWM event chronology")
        if type(guest_wfi) is not int or guest_wfi < 1:
            raise ValueError("Native Guest WFI is required")
        if type(observed_virtual_ns) is not int:
            raise TypeError("Native QEMU observed virtual time required")
        unseen = [r for r in history.events if
                  r["sequence"] >= self.next_sequence]
        for event in unseen:
            if event["sequence"] != self.next_sequence:
                raise ValueError("PWM historical sequence gap before motor integration")
            if event["old_mask"] != self.last_mask or (
                    not event["internal_level_evaluator_valid"]):
                raise ValueError("PWM historical levels invalid or discontinuous")
            self._advance(event["virtual_ns"])
            mode = _topology(
                event["new_mask"], enabled=_raw_gate_enabled(event))
            if mode != self.motor.topology:
                self.event_topology_changes += 1
            self.motor.set_switches(mode)
            self.last_mask = event["new_mask"]
            self.next_sequence += 1
            self.records_consumed += 1
        if self.last_mask != history.last_mask:
            raise ValueError("Original QEMU live mask disagrees with event journal")
        if not history.polls or history.polls[-1]["wfi"] != guest_wfi:
            raise ValueError("Original Guest WFI history not at requested checkpoint")
        self._advance(observed_virtual_ns)
        self.last_sample = self.motor.sample(
            gate_enabled=any(x != "Z" for x in self.motor.topology.legs))
        return self.last_sample

    def inject_bemf(self, read32, write32):
        """QEMU-only three phase analog fixture; no Guest or IRQ writes."""
        if self.records_consumed == 0 or self.last_time_ns is None:
            raise ValueError("No verified actual PWM history to inject from")
        words = self.frontend.words(self.last_sample)  # check range FIRST
        if any((word & ~0x10fff) != 0 or not word & 0x10000
               for word in words):
            raise ValueError("Invalid physical frontend voltage codes")
        for phase, word in enumerate(words):
            write32(SIM_BEMF_INPUT + 4 * phase, word)
        for phase, word in enumerate(words):
            if read32(SIM_BEMF_INPUT + 4 * phase) != word:
                raise AssertionError("QEMU comparator analog sample readback failure")
        self.analog_samples += 1
        self.last_injected_voltage_words = tuple(words)
        return words

    @staticmethod
    def virtual_time_at_guest_wfi(read32) -> int:
        """Read only the QEMU virtual clock snapshot on the PWM observer."""
        before = read32(SWITCH_BASE + 0x24)
        high = read32(SWITCH_BASE + 0x28)
        after = read32(SWITCH_BASE + 0x24)
        if after < before:
            high2 = read32(SWITCH_BASE + 0x28)
            if high2 != high + 1:
                raise ValueError("PWM clock snapshot tore across rollover")
            high = high2
        return (high << 32) | after

    def evidence(self):
        d=self.motor.diagnostics()
        return {
            "status":"OPEN_INDEPENDENT_STRICT_NATIVE_ROTOR_STILL_REQUIRED",
            "original_pwm_source":self.source,
            "motor_profile":self.motor_profile,
            "guest_sram_irq_pwm_register_writes":False,
            "qemu_analog_fixture_writes_only":True,
            "actual_clocked_pwm_events":self.records_consumed,
            "actual_topology_transitions":self.event_topology_changes,
            "native_wfi_analog_injections":self.analog_samples,
            "physical_model_integrated_ns":self.total_integrated_ns,
            "instantaneous_leg_model_only":True,
            "calibrated_motor":False,
            "voltage_input_codes":self.last_injected_voltage_words,
            "rotor_rpm_model_only":self.last_sample.mechanical_rpm,
            "model_energy":d,
        }
