#!/usr/bin/env python3
"""G16 minimal Host CLI: select a motor + provision original Guest telemetry poles.

This is SIM_ONLY pre-boot Flash-Cfg provisioning, NOT a Guest UART CLI.
All bytes are extracted from the pinned original ELF, and exactly one
mutable Cfg field (telem_poles) is changed. No Guest SRAM, app ELF,
firmware control/timing fields or original source config image are modified.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.native_motor_model_profiles import (
    DATASHEET_PROFILES, native_motor_parameters, native_motor_model_metadata)
from tools.native_sim_cfg_flash import extract_cfgdata, FLASH_CFG

# Verified against original Rel17.3 src/common.h Cfg layout:
# ID[0:2], rev[2:4], name[4:19], _null[19], then packed fields,
# five uint16 throttle/analog fields and 6 one-byte input/telemetry fields.
TELEM_POLES_CFG_OFFSET = 57


def build_profile_cfg_flash(elf_bytes: bytes, profile: str):
    if profile not in DATASHEET_PROFILES:
        raise ValueError("Only documented ECX87 motor profiles may provision Cfg")
    original = extract_cfgdata(elf_bytes)
    poles = native_motor_parameters(profile).pole_pairs * 2
    if (len(original) <= TELEM_POLES_CFG_OFFSET or
            not 2 <= poles <= 100 or
            not 2 <= original[TELEM_POLES_CFG_OFFSET] <= 100):
        raise ValueError("Original Rel17.3 Cfg telem_poles ABI not verifiable")
    cfg = bytearray(original)
    prior = cfg[TELEM_POLES_CFG_OFFSET]
    cfg[TELEM_POLES_CFG_OFFSET] = poles
    differing = [i for i, (a, b) in enumerate(zip(original, cfg)) if a != b]
    if differing not in ([], [TELEM_POLES_CFG_OFFSET]):
        raise AssertionError("Unexpected Guest Cfg fields changed")
    image = bytes(cfg) + b"\xff" * ((-len(cfg)) % 8)
    return image, {
        "scope": "SIM_ONLY_PREBOOT_FLASH_CFG_NOT_ORIGINAL_GUEST_UART_CLI",
        "original_guest_elf_unchanged": True,
        "cfg_flash_base": f"0x{FLASH_CFG:08x}",
        "motor_profile": profile,
        "original_cfg_sha256": hashlib.sha256(original).hexdigest(),
        "provisioned_cfg_sha256": hashlib.sha256(cfg).hexdigest(),
        "changed_cfg_fields": (
            ["telem_poles"] if differing else []),
        "telem_poles_cfg_offset": TELEM_POLES_CFG_OFFSET,
        "telem_poles_before": prior,
        "telem_poles_after": poles,
        "cfg_image_bytes": len(image),
        "motor_model": native_motor_model_metadata(profile),
        "not_a_native_cli_or_firmware_control_policy_change": True,
    }


def require_matching_profile_cfg(elf_bytes: bytes, image: bytes, profile: str):
    """Fail closed rather than pairing wrong Guest poles and motor plant."""
    expected, meta = build_profile_cfg_flash(elf_bytes, profile)
    if image != expected:
        raise ValueError(
            "SIM_ONLY Cfg Flash does not exactly match original ELF + "
            "selected motor profile telem_poles; regenerate profile image")
    return meta


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sim-only-opt-in", action="store_true", required=True)
    p.add_argument("--elf", type=Path, required=True)
    p.add_argument("--motor-profile", choices=DATASHEET_PROFILES, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if ("g13b3" not in a.output.name.lower() or
            a.output.suffix != ".bin" or
            not a.elf.is_file()):
        p.error("Require genuine ELF and dedicated g13b3 SIM_ONLY .bin output")
    image, meta = build_profile_cfg_flash(a.elf.read_bytes(), a.motor_profile)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(image)
    print("PASS_G16_SIM_ONLY_MOTOR_PROFILE_GUEST_TELEM_POLES " +
          json.dumps(meta, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
