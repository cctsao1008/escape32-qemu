#!/usr/bin/env python3
"""G13B3L opt-in SIM_ONLY original-Cfg startup initializer.

Original AM13E config.ld places Cfg cfg in a NOLOAD SRAM section: QEMU
application-only boot cannot inherit the real system's config/Boot setup.
For a SEPARATE SIM_ONLY ELF *only*, merge the exact .cfg input section
into the ordinary .data program image. The original TI Reset_Handler
copies the compiler-provided cfg initializer from FLASH_APP into RAM_S.
This never writes Guest SRAM via host debugger, QTest or a fake ISR.

MUST NOT be selected by a production E62/Boot build. Fail closed if
the pinned TI linker script shape changes.
"""
from pathlib import Path
import argparse

_ORIGINAL = """    .data : {
        __data_start__ = .;
        *(.data .data.*)
        . = ALIGN(4);
        __data_end__ = .;
    } > RAM_S AT> FLASH_APP
    __data_load__ = LOADADDR(.data);
    .cfg (NOLOAD) : {
        . = ALIGN(8);
        _cfg_start = .;
        KEEP(*(.cfg))
        . = ALIGN(8);
        _cfg_end = .;
    } > RAM_S
"""

_SIM_ONLY = """    /*
     * G13B3L SIM_ONLY original Application start: there is no native
     * Boot/config partition handoff in the QEMU Application-only test.
     * Initialize the SAME original ESCape32 Cfg cfg from its own compiled
     * defaults, through the unchanged TI Reset_Handler .data loader.
     * Gate, Trip, BEMF, Rel17 duty and commutation logic all unchanged.
     * NEVER use as E62 production Cfg persistence/recovery policy.
     */
    .data : {
        __data_start__ = .;
        *(.data .data.*)
        . = ALIGN(8);
        _cfg_start = .;
        KEEP(*(.cfg))
        . = ALIGN(8);
        _cfg_end = .;
        __data_end__ = .;
    } > RAM_S AT> FLASH_APP
    __data_load__ = LOADADDR(.data);
"""


def derive_sim_cfg_startup(source: str) -> str:
    if source.count(_ORIGINAL) != 1:
        raise ValueError("Pinned original AM13E .cfg/.data script mismatch")
    if source.count("KEEP(*(.cfg))") != 1 or source.count(".cfg (NOLOAD)") != 1:
        raise ValueError("Original Linker has unexpected second .cfg")
    if "__app_flash_payload_end__ = LOADADDR(.data)+SIZEOF(.data);" not in source:
        raise ValueError("Original flash payload extent no longer includes .data")
    if "ASSERT(_cfg_end-_cfg_start<=LENGTH(FLASH_CFG1)" not in source:
        raise ValueError("Original config bounds assertion missing")
    result = source.replace(_ORIGINAL, _SIM_ONLY)
    if ".cfg (NOLOAD)" in result or result.count("KEEP(*(.cfg))") != 1:
        raise AssertionError("Original no-load config not uniquely relocated")
    return result


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--sim-only-opt-in", action="store_true", required=True)
    cli.add_argument("--linker", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    a = cli.parse_args()
    if (a.output == a.linker or not a.linker.is_file() or
        "simcfg" not in str(a.output)):
        raise ValueError("Use isolated G13B3L simcfg linker output")
    result = derive_sim_cfg_startup(a.linker.read_text())
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(result)
    print("PASS_G13B3L_SOURCE_DEFINED_CFG_TI_RESET_HANDLER_SIM_ONLY")

if __name__ == "__main__":
    main()
