#!/usr/bin/env python3
"""G13B3C preflight: read-only original CMPSS0/ECAP1 BEMF arm diagnosis.

Consumes the original guest-owned BEMF selected_code and armed flag.
No synthetic comparator edges or guessed phase selection are emitted.
No claim of actual zero crossing, IRQ processing, commutation or motion.
"""
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable
import re
import subprocess

CMPSS0 = 0x40460000
ECAP1 = 0x40441000
SYS_HP_MUX = 0x400B0444
ECAP_POWER = 0x400B0424
BEMF_CMP0_POWER = 1 << 10
BEMF_ECAP1_POWER = 1 << 4


@dataclass(frozen=True)
class NativeBemfArmSymbolAudit:
    """A symbol address, never an assertion that guest capture is armed."""
    address: int | None
    reason: str
    candidates: tuple[dict, ...]

    def to_dict(self):
        return asdict(self)


def audit_native_bemf_arm_nm(output: str) -> NativeBemfArmSymbolAudit:
    """Identify original motor_bemf.c static armed, fail closed on ambiguity.

    Some GCC versions append .N to file-static names. nm -l may supply
    source file/line; never select an ambiguous address by ordering.
    """
    pattern = re.compile(
        r"^([0-9a-fA-F]{8,16})\s+([0-9a-fA-F]{8,16})\s+"
        r"([bBdD])\s+(armed(?:\.\d+)?)(?:\s+(.*))?$"
    )
    candidates = []
    for line in output.splitlines():
        m = pattern.fullmatch(line.strip())
        if m:
            candidates.append(dict(
                name=m[4], address=int(m[1], 16),
                size=int(m[2], 16), source=(m[5] or "").strip()
            ))
    valid = [c for c in candidates
             if 0x20000000 <= c["address"] < 0x20020000
             and c["size"] == 4]
    if not valid:
        return NativeBemfArmSymbolAudit(
            None, "no addressable 4-byte SRAM armed symbol",
            tuple(candidates))
    if len(valid) == 1:
        chosen = valid[0]
        if chosen["source"] and "motor_bemf.c" not in chosen["source"]:
            return NativeBemfArmSymbolAudit(
                None, "sole armed symbol belongs to another source",
                tuple(candidates))
    else:
        scoped = [c for c in valid if "motor_bemf.c" in c["source"]]
        if len(scoped) != 1 or not all(c["source"] for c in valid):
            return NativeBemfArmSymbolAudit(
                None, "multiple armed symbols; source ambiguous",
                tuple(candidates))
        chosen = scoped[0]
    return NativeBemfArmSymbolAudit(
        chosen["address"], "unique original native BEMF armed SRAM symbol",
        tuple(candidates))


def audit_native_bemf_arm_elf(
    elf: str | Path, nm: str = "arm-none-eabi-nm"
) -> NativeBemfArmSymbolAudit:
    """Read ELF symbols only; no guest access and no firmware changes."""
    output = subprocess.run(
        [nm, "-a", "-S", "-l", "-n", str(elf)],
        check=True, capture_output=True, text=True, timeout=15
    ).stdout
    return audit_native_bemf_arm_nm(output)


@dataclass(frozen=True)
class NativeBemfReadiness:
    selected_code: int
    native_capture_armed: bool
    selected_phase: int | None
    expected_edge_falling: bool | None
    actual_hp_mux: int
    compctl: int
    active_dac_code: int
    ecap_input: int
    ecctl1: int
    ecctl2: int
    eceint: int
    channel_ready_for_voltage_samples: bool
    reason: str

    def to_dict(self):
        return asdict(self)


def observe_original_bemf_route(
    read32: Callable[[int], int], *, selected_code: int,
    native_armed: bool
) -> NativeBemfReadiness:
    """Check native high comparator/ECAP1 route; never enable it.

    Rel17 compctl(x): (x&3)=1..3 selects HP0..2; x&4 reverses
    edge polarity. ECAP captures falling edge when x&4=0, rising
    otherwise; this is deliberately not symmetric with comparator raw.
    """
    selected_phase = ((selected_code & 3) - 1
                      if 0 < (selected_code & 3) <= 3 and
                      0 <= selected_code <= 7 else None)
    # x&4: guest selects rising, else falling. ECCTL1.CEVT1POL bit0
    expected_falling = (not bool(selected_code & 4)
                        if selected_phase is not None else None)
    mux = read32(SYS_HP_MUX) & 7
    compctl = read32(CMPSS0) & 0xffff
    dach = (read32(CMPSS0 + 0x0c) >> 16) & 0xfff
    ecctl0 = read32(ECAP1 + 0x24)
    ecctl = read32(ECAP1 + 0x28)
    ecctl1 = ecctl & 0xffff
    ecctl2 = (ecctl >> 16) & 0xffff
    eceint = read32(ECAP1 + 0x2c) & 0xffff
    power = read32(ECAP_POWER)
    reasons = []
    if selected_phase is None:
        reasons.append("guest has no valid Rel17 phase selection")
    if not native_armed:
        reasons.append("native BEMF capture has not armed")
    if (power & (BEMF_CMP0_POWER | BEMF_ECAP1_POWER)) != (
            BEMF_CMP0_POWER | BEMF_ECAP1_POWER):
        reasons.append("CMPSS0 or ECAP1 unpowered")
    if selected_phase is not None and mux != selected_phase:
        reasons.append("native high-input phase mux differs from selected_code")
    if (compctl & 0x8000) == 0 or (compctl & 0x000c) != 0x0008:
        reasons.append("native CMPSS0 high filtered comparator not enabled")
    if not 0 < dach < 4096:
        reasons.append("native BEMF neutral DAC inactive")
    if ecctl0 & 0x7f != 45:
        reasons.append("ECAP1 not routed to CMPSS0 CTRIPH Input45")
    if not (ecctl1 & 0x100):
        reasons.append("ECAP1 CAPLDEN not enabled")
    if not (ecctl2 & 0x10):
        reasons.append("ECAP1 timestamp counter not running")
    if not (eceint & 0x2):
        reasons.append("native ECAP1 capture event interrupt disabled")
    if expected_falling is not None and bool(ecctl1 & 1) != expected_falling:
        reasons.append("ECAP1 edge polarity mismatches Rel17 compctl")
    return NativeBemfReadiness(
        selected_code=selected_code,
        native_capture_armed=native_armed,
        selected_phase=selected_phase,
        expected_edge_falling=expected_falling,
        actual_hp_mux=mux, compctl=compctl,
        active_dac_code=dach,
        ecap_input=ecctl0 & 0x7f,
        ecctl1=ecctl1, ecctl2=ecctl2, eceint=eceint,
        channel_ready_for_voltage_samples=not reasons,
        reason="; ".join(reasons) if reasons else
               "original BEMF comparator/capture fully armed"
    )
