#!/usr/bin/env python3
"""G13B3D: observed native PWM -> time-coupled *host* VirtualBLDC.

At each original guest stop, sample the *running native* ECAP1 TSCTR and
qualified original AQ/DB six-output observer. Advance the independent
plant by the elapsed ECAP ticks, NOT wall time, GDB step counts, or a
host-written QEMU clock. This is a sampled zero-order-hold approximation:
a changed output image makes the intervening interval unknowable and it
is recorded, but NEVER silently integrated as unchanged PWM.

No write32 or simulator feedback callback exists in this class.
No native ECAP IRQ / zero crossing / closed-loop claim is made.
"""
from dataclasses import asdict, dataclass
from typing import Callable

from .native_pwm_qualification import observe_original_pwm
from .virtual_bldc import VirtualBLDC

ECAP1_TSCTR = 0x40441000
NATIVE_ECAP_CLOCK_HZ = 200_000_000


@dataclass(frozen=True)
class NativePwmTimelineFrame:
    index: int
    checkpoint: str
    native_ecap_ticks: int
    elapsed_ticks: int
    elapsed_ns: int
    delta_ticks: int
    interval_integrated_ns: int
    total_integrated_ns: int
    pwm_period_ticks: int
    six_high_ticks: tuple[int, int, int, int, int, int]
    six_duties: tuple[float, float, float, float, float, float]
    pwm_image_changed: bool
    mechanical_rpm: float
    phase_currents_a: tuple[float, float, float]
    bemf_phase_v: tuple[float, float, float]
    qualifier: str

    def to_dict(self):
        return asdict(self)


class NativePwmTimeline:
    """Pure host plant integration from bounded native ECAP1 observations."""

    def __init__(self, motor: VirtualBLDC, *,
                 ecap_hz: int = NATIVE_ECAP_CLOCK_HZ,
                 max_delta_ticks: int = 200_000,
                 integrate_sampled_hold: bool = True):
        if (not isinstance(ecap_hz, int) or ecap_hz <= 0
                or 1_000_000_000 % ecap_hz):
            raise ValueError("Native ECAP timebase must resolve whole ns")
        if (not isinstance(max_delta_ticks, int)
                or not 0 < max_delta_ticks < 0x80000000):
            raise ValueError("Native timeline bound must be positive")
        self.motor = motor
        if type(integrate_sampled_hold) is not bool:
            raise TypeError("Explicit sampled-duty model policy required")
        self.integrate_sampled_hold = integrate_sampled_hold
        self.ecap_hz = ecap_hz
        self.max_delta_ticks = max_delta_ticks
        self.frames: list[NativePwmTimelineFrame] = []
        self._last_image = None
        self.last_observation = None  # the current accepted guest/MMIO snapshot
        self._last_tick = None
        self._elapsed_ticks = 0
        self._integrated_ns = 0

    @property
    def integrated_intervals(self) -> int:
        return sum(f.interval_integrated_ns > 0 for f in self.frames)

    @property
    def changed_intervals(self) -> int:
        return sum(f.pwm_image_changed for f in self.frames)

    def observe(self, read32: Callable[[int], int], *,
                native_ticks: int, checkpoint: str) -> NativePwmTimelineFrame:
        if not isinstance(native_ticks, int) or not 0 <= native_ticks <= 0xffffffff:
            raise ValueError("Native ECAP1 TSCTR must be a 32-bit value")
        if not checkpoint:
            raise ValueError("An observed native stop checkpoint is required")
        image = observe_original_pwm(read32, gate_active_level=1)
        if not image.acceptable_for_plant or image.six_duties is None:
            raise ValueError("Unsafe/unqualified native PWM: " + image.reason)

        delta = 0
        changed = False
        integrated = 0
        if self._last_tick is not None:
            delta = (native_ticks - self._last_tick) & 0xffffffff
            if not 0 < delta <= self.max_delta_ticks:
                raise ValueError(
                    "Native ECAP time interval invalid/too large: "
                    f"delta_ticks={delta} max={self.max_delta_ticks}")
            changed = (image.period_ticks != self._last_image.period_ticks or
                       image.six_high_ticks != self._last_image.six_high_ticks)
            # Never assign a new image retroactively to an unknown interval.
            # Identical sampled endpoints are a sampled-hold assumption,
            # NOT proof of no intermediate PWM transition.
            if not changed and self.integrate_sampled_hold:
                integrated = delta * (1_000_000_000 // self.ecap_hz)
                self.motor.advance(
                    self._last_image.six_duties,
                    integrated / 1_000_000_000,
                    gate_enabled=True)

        self._elapsed_ticks += delta
        self._integrated_ns += integrated
        sample = self.motor.sample(gate_enabled=True)
        frame = NativePwmTimelineFrame(
            index=len(self.frames),
            checkpoint=checkpoint,
            native_ecap_ticks=native_ticks,
            elapsed_ticks=self._elapsed_ticks,
            elapsed_ns=self._elapsed_ticks * (1_000_000_000 // self.ecap_hz),
            delta_ticks=delta,
            interval_integrated_ns=integrated,
            total_integrated_ns=self._integrated_ns,
            pwm_period_ticks=image.period_ticks,
            six_high_ticks=image.six_high_ticks,
            six_duties=image.six_duties,
            pwm_image_changed=changed,
            mechanical_rpm=sample.mechanical_rpm,
            phase_currents_a=sample.phase_currents_a,
            bemf_phase_v=sample.bemf_phase_v,
            qualifier=("EXTERNAL_CLOCKED_CURRENT_CONTINUOUS_NO_AVERAGE"
                       if not self.integrate_sampled_hold else
                       "PWM_CHANGE_UNRESOLVED_INTERVAL" if changed else
                       "NATIVE_START_SNAPSHOT" if self._last_tick is None
                       else "SAMPLED_HOLD_INTERVAL"),
        )
        self.frames.append(frame)
        self._last_tick = native_ticks
        self._last_image = image
        # The caller can reuse the already-qualified observation at this
        # exact stopped-WFI checkpoint; no second MMIO sweep is needed.
        self.last_observation = image
        return frame

    def require_progress(self, *, min_frames: int = 4,
                         min_integrated_intervals: int = 2):
        if (len(self.frames) < min_frames or
                self.integrated_intervals < min_integrated_intervals or
                self._integrated_ns <= 0):
            raise AssertionError(
                "Native continuous PWM/time-coupled plant insufficient: "
                f"frames={len(self.frames)}, "
                f"integrated={self.integrated_intervals}, "
                f"unknown_changes={self.changed_intervals}")
        return {
            "frames": len(self.frames),
            "integrated_intervals": self.integrated_intervals,
            "unknown_pwm_change_intervals": self.changed_intervals,
            "native_elapsed_ticks": self._elapsed_ticks,
            "native_elapsed_ns":
                self._elapsed_ticks * (1_000_000_000 // self.ecap_hz),
            "plant_integrated_ns": self._integrated_ns,
            "feedback_injected": False,
            "timestamp_source": "ORIGINAL_ECAP1_TSCTR_200MHZ",
            "assumption": "SAMPLED_ZERO_ORDER_HOLD_NOT_FULL_WAVEFORM"
        }
