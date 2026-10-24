#!/usr/bin/env python3
"""Opt-in, read-only original-Guest WFI trace for the E62 offline workbench.

Consumes ALREADY sampled native PWM, ECAP, Guest counters and host plant.
It never owns an RSP/QTest socket, advances a clock, or qualifies a motor.
A WFI PWM high-tick count is a carrier-average sample, NOT pin-edge VCD.
"""
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

from .native_pwm_history_collector import NativeWfiPWMHistoryCollector

FORMAT = "e62.sitl.native-wfi.v1"
NS_PER_ECAP_TICK = 5  # Native ECAP1, functional 200 MHz SIM_ONLY
SCOPE = "SIM_ONLY_UNCALIBRATED_OPEN_STAR_MODEL"


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite(values, label, count):
    values = list(values)
    if len(values) != count or not all(
            isinstance(value, (int, float)) and
            math.isfinite(value) for value in values):
        raise ValueError(f"{label} must contain {count} finite numbers")
    return values


class SitlTraceRecorder:
    """Zero extra Guest/MMIO queries: one immutable snapshot per observed WFI."""

    def __init__(self, *, elf_sha256, initial_electrical_degrees,
                 required_sectors, required_integrated_ns, motor_model=None):
        if len(elf_sha256) != 64 or any(c not in "0123456789abcdef" for c in elf_sha256):
            raise ValueError("Actual original ELF SHA256 is required")
        self.meta = {
            "elf_sha256": elf_sha256,
            "initial_electrical_degrees": initial_electrical_degrees,
            "required_sectors": required_sectors,
            "required_integrated_ns": required_integrated_ns,
            "host_guest_register_writes": False,
        }
        if motor_model is not None:
            if not isinstance(motor_model, dict) or motor_model.get(
                    "scope") != "SIM_ONLY_UNCALIBRATED_AB_EXPERIMENT":
                raise ValueError("Unknown SIM_ONLY motor model provenance")
            self.meta["motor_model"] = dict(motor_model)
        self.origin_ecap_ticks = None
        self.samples = []
        self.events = []
        self._sector_count = 0
        self.native_result = None
        self.pwm_history_collector = None

    def attach_pwm_history(self, collector):
        """Optional read-only QEMU internal event evidence; no native gate."""
        if (not isinstance(collector, NativeWfiPWMHistoryCollector) or
                self.origin_ecap_ticks is None or self.samples or
                self.pwm_history_collector is not None):
            raise ValueError("Native Gate origin and unique PWM collector required")
        self.pwm_history_collector = collector
        self.meta["qemu_internal_history_opt_in"] = True

    def set_gate_origin(self, frame):
        if self.origin_ecap_ticks is not None or self.samples:
            raise ValueError("Gate origin already set")
        if frame.index != 0 or frame.elapsed_ns != 0:
            raise ValueError("Native Gate-return origin must be first ECAP sample")
        self.origin_ecap_ticks = frame.native_ecap_ticks

    def _time_from_ecap(self, tick):
        if not isinstance(tick, int) or not 0 <= tick <= 0xffffffff:
            raise ValueError("Guest ECAP counter must be uint32")
        return ((tick - self.origin_ecap_ticks) & 0xffffffff) * NS_PER_ECAP_TICK

    def observe(self, *, visit, frame, pwm, plant, guest, analog,
                cap1_ticks, sectors, energy_balance=None):
        if self.origin_ecap_ticks is None:
            raise ValueError("Missing actual native Gate ECAP origin")
        if not isinstance(visit, int) or visit != len(self.samples) + 1:
            raise ValueError("WFI observations must be consecutive and ordered")
        if frame.index != visit or frame.checkpoint != f"native_sustained_wfi_{visit}":
            raise ValueError("Frame must come from this exact Guest WFI")
        t_ns = self._time_from_ecap(frame.native_ecap_ticks)
        if t_ns != frame.elapsed_ns or (
                self.samples and t_ns <= self.samples[-1]["t_ns"]):
            raise ValueError("Native ECAP time/rollover not monotonic")
        high = _finite(pwm.six_high_ticks, "original six PWM high ticks", 6)
        if not pwm.acceptable_for_plant or high != list(frame.six_high_ticks):
            raise ValueError("Unqualified or mismatched original PWM snapshot")
        if not isinstance(pwm.period_ticks, int) or pwm.period_ticks <= 0 or any(
                x < 0 or x > pwm.period_ticks for x in high):
            raise ValueError("Invalid original PWM carrier")
        bemf = _finite(plant.bemf_phase_v, "host model BEMF", 3)
        currents = _finite(plant.phase_currents_a, "host model phase currents", 3)
        codes = _finite((word & 0xfff for word in analog), "physical analog codes", 3)
        rpm = _finite([plant.mechanical_rpm], "host model RPM", 1)[0]
        for key in ("step", "selected_code", "armed", "captured_events",
                    "scheduled", "serviced", "rejected_events"):
            if key not in guest or not isinstance(guest[key], int):
                raise ValueError("Original Guest event/state missing: " + key)
        if not 1 <= guest["step"] <= 6:
            raise ValueError("Original Guest step is not a six-step value")
        sample = {
            "wfi": visit,
            "t_ns": t_ns,
            "integrated_ns": frame.total_integrated_ns,
            "native_ecap_ticks": frame.native_ecap_ticks,
            "pwm_period_ticks": pwm.period_ticks,
            "pwm_high_ticks": list(high),
            "pwm_duties": [v / pwm.period_ticks for v in high],
            "guest_step": guest["step"],
            "guest_selected_code": guest["selected_code"],
            "guest_armed": guest["armed"],
            "guest_captured": guest["captured_events"],
            "guest_scheduled": guest["scheduled"],
            "guest_serviced": guest["serviced"],
            "guest_rejected": guest["rejected_events"],
            "cap1_ticks": cap1_ticks,
            "motor_rpm": rpm,
            "electrical_rad": plant.electrical_rad,
            "phase_currents_a": currents,
            "bemf_phase_v": bemf,
            "analog_adc_codes": codes,
            "gate_qualified": pwm.gate_and_pads,
            "ost2": pwm.physical_ost2,
            "ost3": pwm.physical_ost3,
            "sampling_qualifier": frame.qualifier,
        }
        # Reuse the host plant's existing per-integration accumulator.
        # This does not issue another Guest/QTest read or create an event.
        if energy_balance is not None:
            if not isinstance(energy_balance, dict) or energy_balance.get(
                    "scope") != "SIM_ONLY_SAMPLED_HOLD_NUMERICAL_ENERGY_DIAGNOSTIC":
                raise ValueError("Unqualified SIM_ONLY energy ledger provenance")
            if energy_balance.get("numerical_energy_balance_qualified") is not False:
                raise ValueError("Energy ledger cannot assert physical qualification")
            sample["sim_only_energy_balance"] = dict(energy_balance)
        # Fail rather than backfill or fabricate time samples and "clean" states.
        if self.samples and sample["integrated_ns"] < self.samples[-1]["integrated_ns"]:
            raise ValueError("Plant-integrated time regressed")
        if not isinstance(sectors, list) or len(sectors) < self._sector_count:
            raise ValueError("Native accepted-sector list regressed")
        new_events = []
        for index, sector in enumerate(sectors[self._sector_count:],
                                       start=self._sector_count + 1):
            for kind, tick in (
                ("CAP1_ACCEPTED", sector.accepted_cap1_ticks),
                ("TIMG12_SERVICED", sector.serviced_ecap_ticks),
            ):
                event_t = self._time_from_ecap(tick)
                if event_t > t_ns:
                    raise ValueError("Accepted Guest event is newer than WFI")
                new_events.append({
                    "kind": kind,
                    "sector": index,
                    "t_ns": event_t,
                    "source_native_ecap_ticks": tick,
                    "observed_at_wfi": visit,
                    "guest_step_before": sector.guest_step_before,
                    "guest_step_after": sector.guest_step_after,
                })
        self.samples.append(sample)
        self.events.extend(new_events)
        self._sector_count = len(sectors)
        # Return the already validated, immutable-at-publication payload
        # to an optional telemetry consumer. No duplicate Guest/MMIO read.
        return {"sample": sample, "events": new_events}

    def finish(self, result):
        if not isinstance(result, dict):
            raise ValueError("Native result required")
        motion = result.get("sim_only_rotor_motion", {})
        self.native_result = {
            "native_six_step_qualified": result.get("qualified") is True,
            "completed_feedback_powered_sectors":
                result.get("completed_feedback_powered_sectors"),
            "plant_integrated_ns": result.get("plant_integrated_ns"),
            "direction_continuity_qualified_sim_only":
                motion.get("direction_continuity_qualified_sim_only") is True,
            "significant_direction_reversals":
                motion.get("significant_direction_reversals"),
            "sim_only_energy_balance":
                result.get("sim_only_energy_balance"),
            "sim_only_failure_diagnostics":
                result.get("failure_diagnostics"),
            "last_complete_analog_injected_wfi":
                result.get("last_complete_analog_injected_wfi"),
            "failed_native_wfi_visit":
                result.get("failed_native_wfi_visit"),
            "original_early_rejections":
                result.get("original_early_rejections"),
            "original_rejection_window_resets":
                result.get("original_rejection_window_resets"),
            "extended_strict_verdict": "NOT_EXECUTED_BY_TRACE_RECORDER",
            "physical_motor_stability_qualified": False,
        }

    def document(self, *, error_type=None):
        document = {
            "format": FORMAT,
            "scope": SCOPE,
            "data_semantics": {
                "time": "ECAP1 200MHz ticks relative to original native Gate return",
                "pwm": "SAMPLED per-carrier six HIGH-tick averages, NOT edge waveform",
                "bemf": "host VirtualBLDC physical model predictions, NOT measured voltages",
                "capture_events": "accepted original Guest CAP1/TIMG12 evidence",
                "sampling": "one WFI checkpoint; intermediate PWM transitions unknown",
            },
            "metadata": self.meta,
            "capture_state": ("PARTIAL_EXCEPTION" if error_type else
                              "NATIVE_PROBE_RECORDED"),
            "error_type": error_type,
            "native_result": self.native_result,
            "samples": self.samples,
            "events": self.events,
        }
        if self.pwm_history_collector is not None:
            document["pwm_history"] = self.pwm_history_collector.document()
            document["data_semantics"]["pwm_history"] = (
                "Executed SIM_ONLY QEMU INTERNAL edge callbacks and Guest "
                "MMIO boundaries read at original paused WFI checkpoints; "
                "QEMU virtual ns NOT aligned with native ECAP ns; "
                "NOT external MOSFET gate/power stage waveform")
        return document

    def write(self, path, *, error_type=None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Avoid leaving a malformed partial JSON artifact on failed writes.
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.document(error_type=error_type), stream,
                          indent=None, separators=(",", ":"), allow_nan=False)
                stream.write("\n")
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
