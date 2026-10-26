"""Strict six-pad sector pattern matching for original Rel17 functional SITL.

Do not confuse the PWM source leg's *complementary low side* with a
second independent sink. Derived entirely from six read-only QEMU MCPWM4
per-carrier high-tick counts and an independently pinned expected pair.

This is QEMU average-high-tick topology checking, NOT same-instant shoot-
through, silicon RED/FED timing, gate voltage, or real motor power.
"""
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class OriginalSixPadSectorPattern:
    qualified: bool
    mode: str
    reason: str
    expected_source: int
    expected_sink: int
    floating_phase: int
    source_high_ticks: int
    source_low_ticks: int
    sink_low_ticks: int
    sink_off_ticks: int
    source_high_low_off_ticks: int

    def to_dict(self):
        return asdict(self)


def match_original_rel17_pwm_sector(
        six_high_ticks, *, period_ticks: int, expected_pair
        ) -> OriginalSixPadSectorPattern:
    """Match one of two *distinct* verified six-step six-pad topologies.

    (A) G13 legacy asymmetrical/sink-only case: source H modulates,
        only sink L drives, floating phase H/L off.
    (B) Complementary/synchronous rectification (actual DShot300 trace):
        source H modulates, source L complementary with modeled RED/FED,
        sink L almost full carrier, floating H/L off.

    For mode B, the QEMU observed high tick budgets satisfy:
        source_H + source_L + 2*blanking = period
        sink_L + blanking = period
    Their integer high-tick *averages* only; this cannot establish
    instantaneous nonoverlap. Never infer source/sink from Guest BEMF MUX.
    """
    if (type(period_ticks) is not int or period_ticks <= 0 or
            type(six_high_ticks) not in (tuple, list) or
            len(six_high_ticks) != 6 or
            any(type(v) is not int or not 0 <= v <= period_ticks
                for v in six_high_ticks) or
            type(expected_pair) not in (tuple, list) or
            len(expected_pair) != 2 or
            any(type(x) is not int or not 0 <= x <= 2
                for x in expected_pair) or
            expected_pair[0] == expected_pair[1]):
        raise ValueError("Six valid physical output high-tick counts and distinct expected phases required")
    source, sink = expected_pair
    floating = next(i for i in range(3) if i not in (source, sink))
    src_h = six_high_ticks[2*source]
    src_l = six_high_ticks[2*source+1]
    sink_l = six_high_ticks[2*sink+1]
    sink_h = six_high_ticks[2*sink]
    float_h = six_high_ticks[2*floating]
    float_l = six_high_ticks[2*floating+1]
    sink_off = period_ticks-sink_l
    src_off = period_ticks-src_h-src_l

    def result(ok: bool, mode: str, reason: str):
        return OriginalSixPadSectorPattern(
            qualified=ok, mode=mode, reason=reason,
            expected_source=source, expected_sink=sink,
            floating_phase=floating,
            source_high_ticks=src_h, source_low_ticks=src_l,
            sink_low_ticks=sink_l, sink_off_ticks=sink_off,
            source_high_low_off_ticks=src_off)

    if sink_h or float_h or float_l:
        return result(False, "INVALID", "UNEXPECTED_SINK_HIGH_OR_FLOATING_PAD_ACTIVE")
    if not src_h or not sink_l:
        return result(False, "INVALID", "SOURCE_HIGH_OR_SINK_LOW_ABSENT")
    if src_off < 0:
        return result(False, "INVALID", "SOURCE_HIGH_PLUS_LOW_EXCEEDS_PERIOD")

    # The original QEMU model's active sink still loses ~one RED/FED
    # delay from the period; generous 1% model/quantization tolerance,
    # not a transistor timing/physical nonoverlap assertion.
    if not 0 < sink_off <= max(8, period_ticks // 100):
        return result(False, "INVALID", "SINK_NOT_NEAR_FULL_CARRIER")

    if src_l == 0:
        # Existing legacy fixture: no complementary source low PWM.
        return result(True, "NON_COMPLEMENTARY_SOURCE_H_AND_SINK_L",
                      "ONLY_EXPECTED_SOURCE_HIGH_AND_SINK_LOW")

    # QEMU's two modeled delayed edges leave twice the sink blanking in
    # the source's complementary high+low total. Do not replace this
    # structural check with a loose 'lower phase count' or random tolerance.
    if abs(src_off - 2*sink_off) > max(2, period_ticks // 2000):
        return result(False, "INVALID",
                      "COMPLEMENTARY_PERIOD_BUDGET_INCONSISTENT")
    if src_l >= sink_l:
        return result(False, "INVALID",
                      "COMPLEMENTARY_SOURCE_LOW_NOT_BELOW_SINK_LOW")
    return result(True, "COMPLEMENTARY_SOURCE_H_L_AND_SINK_L",
                  "EXPECTED_THREE_PHASE_BRIDGE_PATTERN")


__all__ = ["OriginalSixPadSectorPattern", "match_original_rel17_pwm_sector"]
