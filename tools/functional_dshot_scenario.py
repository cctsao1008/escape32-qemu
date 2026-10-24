#!/usr/bin/env python3
"""Deterministic *virtual-time* DShot scenario schedule, no Guest I/O.

This compiles intents only. Native receipt/CRC/PWM/BEMF/CAP1/TIMG12 must
be confirmed by a separate original-Guest execution adapter. Neither a
schedule preview nor a mock sender is an ESCape32 firmware PASS.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import json
from pathlib import Path
from typing import Callable, Iterator

NS_PER_SECOND = 1_000_000_000
EXPECTED_SHA = "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"


class ScenarioError(ValueError):
    """Malformed scenario or missed guest-virtual-time input deadline."""


def _decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ScenarioError(f"{name}: expected finite numeric value")
    try:
        out = Decimal(str(value))
    except InvalidOperation as exc:
        raise ScenarioError(f"{name}: invalid number") from exc
    if not out.is_finite():
        raise ScenarioError(f"{name}: nonfinite number")
    return out


def _int_nanoseconds(seconds: object, name: str) -> int:
    ns = _decimal(seconds, name) * NS_PER_SECOND
    if ns != ns.to_integral_value() or ns <= 0:
        raise ScenarioError(f"{name}: expected positive exact whole nanoseconds")
    return int(ns)


def percent_to_dshot(pct: object) -> int:
    """0% is neutral (0); positive commands are 48..2047, half-even round."""
    p = _decimal(pct, "throttle_pct")
    if not 0 <= p <= 100:
        raise ScenarioError("throttle_pct outside [0,100]")
    if p == 0:
        return 0
    return int((Decimal(48) + Decimal(1999) * p / 100).quantize(
        Decimal(1), rounding=ROUND_HALF_EVEN))


@dataclass(frozen=True)
class Stage:
    index: int
    kind: str
    start_ns: int
    end_ns: int
    from_pct: Decimal
    to_pct: Decimal
    update_ns: int

    def percentage_at(self, time_ns: int) -> Decimal:
        if not self.start_ns <= time_ns < self.end_ns:
            raise ScenarioError("Out-of-stage virtual time")
        if self.kind == "hold":
            return self.to_pct
        elapsed = time_ns - self.start_ns
        # Ramps are discrete command updates, not continuous analogue PWM.
        elapsed = (elapsed // self.update_ns) * self.update_ns
        return self.from_pct + (self.to_pct-self.from_pct) * (
            Decimal(elapsed) / Decimal(self.end_ns-self.start_ns))


@dataclass(frozen=True)
class FrameIntent:
    frame_index: int
    stage_index: int
    scheduled_ns: int
    pct: Decimal
    dshot_value: int

    def as_dict(self) -> dict:
        return {"frame_index": self.frame_index,
                "stage_index": self.stage_index,
                "scheduled_virtual_ns": self.scheduled_ns,
                "throttle_pct": float(self.pct),
                "dshot_value": self.dshot_value}


@dataclass(frozen=True)
class Scenario:
    case_id: str
    name: str
    frame_rate_hz: int
    frame_period_ns: int
    stages: tuple[Stage, ...]
    duration_ns: int
    pinned_elf_sha256: str

    @property
    def total_frames(self) -> int:
        return self.duration_ns // self.frame_period_ns

    def frame(self, index: int) -> FrameIntent:
        if not isinstance(index, int) or not 0 <= index < self.total_frames:
            raise ScenarioError("Frame index outside test duration")
        t_ns = index * self.frame_period_ns
        stage = next((s for s in self.stages if t_ns < s.end_ns), None)
        if stage is None:
            raise ScenarioError("Frame time not covered by a stage")
        pct = stage.percentage_at(t_ns)
        return FrameIntent(index, stage.index, t_ns, pct,
                           percent_to_dshot(pct))

    def frames(self) -> Iterator[FrameIntent]:
        for i in range(self.total_frames):
            yield self.frame(i)

    def summary(self) -> dict:
        return {
            "scope": "DECLARATIVE_VIRTUAL_TIME_DSHOT_INTENTS_ONLY_NOT_NATIVE_EXECUTION",
            "case_id": self.case_id,
            "name": self.name,
            "pinned_elf_sha256": self.pinned_elf_sha256,
            "virtual_duration_ns": self.duration_ns,
            "frame_rate_hz": self.frame_rate_hz,
            "frame_count": self.total_frames,
            "host_sleep_driven": False,
            "native_guest_executed": False,
            "firmware_crc_verified": False,
            "functional_closed_loop_qualified": False,
            "stages": [
                {"index": s.index, "kind": s.kind,
                 "start_ns": s.start_ns, "end_ns": s.end_ns,
                 "from_pct": float(s.from_pct), "to_pct": float(s.to_pct)}
                for s in self.stages],
        }


def load_scenario(path: str | Path, case_id: str) -> Scenario:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") not in (
            "e62.sitl.dshot.scenario.v1.proposal",
            "e62.sitl.dshot.scenario.v1"):
        raise ScenarioError("Unknown scenario schema")
    if data.get("target", {}).get("target_elf_sha256") != EXPECTED_SHA:
        raise ScenarioError("Scenario target original ELF SHA mismatch")
    if data.get("clock", {}).get("scenario_clock") != "guest_virtual_elapsed_time" or (
            data["clock"].get("host_sleep_driven") is not False):
        raise ScenarioError("Only guest virtual elapsed clock is permitted")
    conf = data.get("dshot", {})
    if (conf.get("protocol") != "DSHOT600" or conf.get("crc_required") is not True or
            conf.get("percentage_mapping", {}).get("zero_pct_frame_value") != 0 or
            conf.get("percentage_mapping", {}).get("positive_pct_min_frame_value") != 48 or
            conf.get("percentage_mapping", {}).get("positive_pct_max_frame_value") != 2047):
        raise ScenarioError("Unsupported DShot framing or mapping")
    rate = conf.get("nominal_frame_rate_hz")
    if type(rate) is not int or not 1 <= rate <= 2000 or NS_PER_SECOND % rate:
        raise ScenarioError("Frame rate must yield an exact integer ns period")
    period = NS_PER_SECOND // rate
    selected = [s for s in data.get("scenarios", []) if s.get("id") == case_id]
    if len(selected) != 1:
        raise ScenarioError("Expected exactly one matching scenario case")
    raw = selected[0]
    if raw.get("stage_time_origin") != "after_original_firmware_zero_dshot_arming":
        raise ScenarioError("Scenario may not bypass the original 250ms arming")
    stages: list[Stage] = []
    offset = 0
    for i, item in enumerate(raw.get("stages", [])):
        kind = item.get("kind")
        duration = _int_nanoseconds(item.get("duration_s"), "duration_s")
        if duration % period:
            raise ScenarioError("Stage duration must align to DShot frame period")
        if kind == "ramp":
            p0 = _decimal(item.get("from_pct"), "from_pct")
            p1 = _decimal(item.get("to_pct"), "to_pct")
            update = _decimal(item.get("update_period_ms"), "update_period_ms")
            update_ns = update * 1_000_000
            if (update_ns != update_ns.to_integral_value() or
                    update_ns < period or duration % int(update_ns) or
                    int(update_ns) % period or item.get("interpolation") != "linear"):
                raise ScenarioError("Ramp update must align to full frame intervals")
            update_ns = int(update_ns)
        elif kind == "hold":
            p0 = p1 = _decimal(item.get("throttle_pct"), "throttle_pct")
            update_ns = period
        else:
            raise ScenarioError(f"Unsupported stage kind {kind!r}")
        percent_to_dshot(p0)
        percent_to_dshot(p1)
        stages.append(Stage(i, kind, offset, offset+duration, p0, p1,
                            update_ns))
        offset += duration
    if not stages:
        raise ScenarioError("Scenario has no stages")
    expected_ns = _int_nanoseconds(raw.get("expected_test_duration_s"),
                                   "expected_test_duration_s")
    if offset != expected_ns:
        raise ScenarioError("Stage sum differs from declared test duration")
    return Scenario(case_id, raw["name"], rate, period,
                    tuple(stages), offset, EXPECTED_SHA)


class VirtualTimeDShotSequencer:
    """Fail-closed WFI-facing sender; timestamps must be GUEST clock time.

    sender(value) MUST inject one externally clocked PA26 frame and return;
    subsequent native callback/CRC/throttle checks belong to the caller.
    Late command frames are NOT silently compressed or forged.
    """
    def __init__(self, scenario: Scenario, sender: Callable[[int], object],
                 *, max_lateness_ns: int = 500_000):
        if type(max_lateness_ns) is not int or not 0 <= max_lateness_ns < scenario.frame_period_ns:
            raise ScenarioError("Lateness guard must be below one frame period")
        self.scenario = scenario
        self.sender = sender
        self.max_lateness_ns = max_lateness_ns
        self.next_index = 0
        self.last_observed_ns = -1

    @property
    def complete(self) -> bool:
        return self.next_index == self.scenario.total_frames

    def poll(self, elapsed_guest_virtual_ns: int) -> dict | None:
        if type(elapsed_guest_virtual_ns) is not int or elapsed_guest_virtual_ns < 0:
            raise ScenarioError("Guest elapsed time must be nonnegative integer ns")
        if elapsed_guest_virtual_ns < self.last_observed_ns:
            raise ScenarioError("Guest virtual time regressed")
        self.last_observed_ns = elapsed_guest_virtual_ns
        if self.complete:
            return None
        frame = self.scenario.frame(self.next_index)
        if elapsed_guest_virtual_ns < frame.scheduled_ns:
            return None
        late_ns = elapsed_guest_virtual_ns - frame.scheduled_ns
        if late_ns > self.max_lateness_ns:
            raise ScenarioError(
                f"Virtual DShot frame {frame.frame_index} missed by {late_ns}ns")
        self.sender(frame.dshot_value)
        self.next_index += 1
        return {**frame.as_dict(),
                "observed_guest_elapsed_ns": elapsed_guest_virtual_ns,
                "lateness_ns": late_ns,
                "scope": "EXTERNAL_WIRE_SENT_NOT_FIRMWARE_CRC_CONFIRMED"}
