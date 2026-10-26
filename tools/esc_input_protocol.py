"""External ESC input configuration and physical DShot edge plans.

No Guest register/SRAM writes. Acceptance by the original Guest is separate.
Durations are integer nanoseconds, quantized to the 100 MHz TIMG4 clock.
"""
from dataclasses import dataclass
import json
from pathlib import Path

DEFAULT_CONFIG = (Path(__file__).resolve().parents[1] /
                  "configs/e62-functional-input.json")
DSHOT_TICKS = {
    "DSHOT150": (667, 500, 250),
    "DSHOT300": (333, 250, 125),
    "DSHOT600": (167, 125, 63),
}
PROTOCOLS = frozenset((*DSHOT_TICKS, "PWM"))


@dataclass(frozen=True)
class InputConfig:
    protocol: str
    frame_rate_hz: int
    pwm_pulse_width_us: int


def load_input_config(path=None):
    """Read strictly validated external signal selection."""
    location = Path(path) if path is not None else DEFAULT_CONFIG
    raw = json.loads(location.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != "e62.esc-input.v1":
        raise ValueError("Unsupported ESC input config schema")
    if set(raw) != {"schema", "protocol", "dshot", "pwm"}:
        raise ValueError("Unexpected or missing ESC input config fields")
    protocol = raw["protocol"]
    if protocol not in PROTOCOLS:
        raise ValueError("Input protocol must be DSHOT150/300/600 or PWM")
    dshot, pwm = raw["dshot"], raw["pwm"]
    if (not isinstance(dshot, dict) or
            set(dshot) != {"frame_rate_hz"} or
            type(dshot["frame_rate_hz"]) is not int or
            not 100 <= dshot["frame_rate_hz"] <= 2000):
        raise ValueError("Invalid DShot frame rate")
    if (not isinstance(pwm, dict) or
            set(pwm) != {"pulse_width_us"} or
            type(pwm["pulse_width_us"]) is not int or
            not 800 <= pwm["pulse_width_us"] <= 2200):
        raise ValueError("Invalid servo PWM pulse width")
    return InputConfig(protocol, dshot["frame_rate_hz"],
                       pwm["pulse_width_us"])


def dshot_physical_edges(frame, protocol):
    """Return 32 PA26 (delay_ns, level) wire transitions for DShot.

    Original Guest input capture/DMA/parser decides whether to accept.
    This never writes Guest registers or constructs fake IRQ/captures.
    """
    if protocol not in DSHOT_TICKS:
        raise ValueError("Only DShot can produce DShot PA26 edges")
    if type(frame) is not int or not 0 <= frame <= 0xFFFF:
        raise ValueError("DShot frame must be a 16-bit integer")
    period, one_high, zero_high = DSHOT_TICKS[protocol]
    previous_high = 0
    edges = []
    for bit in range(15, -1, -1):
        high = one_high if frame & (1 << bit) else zero_high
        if bit == 15:
            edges.append((10_000, 1))
        else:
            edges.append(((period - previous_high) * 10, 1))
        edges.append((high * 10, 0))
        previous_high = high
    assert len(edges) == 32
    assert all(delay >= 10 and level in (0, 1) for delay, level in edges)
    return tuple(edges)
