#!/usr/bin/env python3
"""G13B0 native Rel17 fail-closed authorization, original unmodified ELF.

No QTest writes, synthetic throttle, GPIO toggles, register manipulation,
board-profile substitution or simulated PWM-to-BEMF injection. The only
RSP write activity is debugger breakpoints and GDB single-stepping
already used in G12. This is a *negative* drive test for the unqualified
Reference firmware, not a claim that DShot/arming/closed-loop works.
"""
import argparse
import json
import re
import subprocess
import tempfile
import sys
from pathlib import Path

# Tests execute from tests/; native bridge modules live in repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elf_image import app_vector_from_elf
from g11_exception_lifecycle import (
    RSP, observer, reach_release, add_bp, del_bp, continue_bounded,
    wait_for_socket
)
from g12_runtime_progress import native_wfi_locations
from tools.virtual_bldc import (
    OBS_BASE, GATE_EN, GPIO1_BASE, PINCM_BASE, MCPWM4_ROUTES,
    gate_and_pads_connected
)

SYS_BASE = 0x400af000
TBCLKSYNC = SYS_BASE + 0x148c
ECAP1 = 0x40441000
STIM = 0x5ffe2000
MCPWM4 = 0x40014000
GPIO0 = 0x400f0000
DMA0 = 0x40090000


def symbol_address(elf: Path, symbol: str, nm="arm-none-eabi-nm") -> int:
    """Resolve an ORIGINAL ELF data symbol, never hard-code SRAM addresses."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", symbol):
        raise ValueError("Invalid symbol")
    out = subprocess.run([nm, "-n", str(elf)], check=True,
                         capture_output=True, text=True, timeout=15).stdout
    hits = []
    for line in out.splitlines():
        m = re.fullmatch(r"([0-9a-fA-F]{8})\s+([bBdD])\s+" +
                         re.escape(symbol), line.strip())
        if m:
            hits.append(int(m.group(1), 16))
    if len(hits) != 1 or not 0x20000000 <= hits[0] < 0x20020000:
        raise RuntimeError(f"Missing/ambiguous native SRAM symbol: {symbol}")
    return hits[0]


def snapshot(rsp: RSP, data_address: dict[str, int]) -> dict:
    read = rsp.mem32
    arch = observer(rsp)
    six = [read(PINCM_BASE + 4 * pin) for pin, _ in MCPWM4_ROUTES]
    pb13_mux = read(PINCM_BASE + 4 * 45)
    result = {
        "arch": arch,
        "firmware": {name: read(addr) for name, addr in data_address.items()},
        "pb13_mapped": pb13_mux,
        "pb13_gpio_doe": read(GPIO1_BASE + 0x12c0),
        "pb13_gpio_dout": read(GPIO1_BASE + 0x1280),
        "six_pincm": six,
        "tbclksync": read(TBCLKSYNC),
        "pwm4_tbctl": read(MCPWM4 + 0x10),
        "pwm_observer_status": read(OBS_BASE),
        "pwm_observer_valid_mask": read(OBS_BASE + 0x14),
        "pwm_observer_high_ticks": [read(OBS_BASE + 0x18 + i * 4)
                                    for i in range(6)],
        "cmp_phase_stimulus": [read(STIM + 4 * i) for i in range(3)],
        "ecap1_cap1": read(ECAP1 + 8),
        "ecap1_event_flags": read(ECAP1 + 0x2c) & 0xffff,
    }
    # Helper's IO ownership proof is *independent* of native code/data:
    # it requires actual PINCM+GPIO+PWM configuration and explicit polarity.
    result["qualified_by_gate_and_pwm_pins"] = gate_and_pads_connected(
        read, gate_active_level=1) or gate_and_pads_connected(
        read, gate_active_level=0)
    return result


def require_no_native_drive(state: dict, label: str):
    if state["arch"]["ipsr"] != 0 or state["arch"]["primask"] != 0:
        raise AssertionError(f"{label}: not in unmasked native Thread")
    if state["arch"]["cfsr"] or state["arch"]["hfsr"]:
        raise AssertionError(f"{label}: CPU fault during no-command runtime")
    if state["firmware"]["throt"] != 0:
        raise AssertionError(f"{label}: native throttle nonzero without input")
    if state["pb13_gpio_doe"] & GATE_EN:
        raise AssertionError(f"{label}: reference firmware drove PB13 gate")
    if state["qualified_by_gate_and_pwm_pins"]:
        raise AssertionError(f"{label}: virtual bridge would allow drive")
    # Assert all six *actual* pad muxes remain GPIO input, rather than
    # relying solely on PB13 being disabled. A surprise PWM pin route
    # is a reference safety regression even if the gate is still off.
    for index, cfg in enumerate(state["six_pincm"]):
        if (cfg & 0x000400bf) != 0x00040081:
            raise AssertionError(
                f"{label}: physical PWM pad {index} unexpectedly connected: "
                f"PINCM=0x{cfg:08x}")
    if state["pwm_observer_status"] & 1:
        raise AssertionError(f"{label}: unexpected running physical PWM output")
    if state["tbclksync"] & 1:
        raise AssertionError(f"{label}: native PWM timebase unexpectedly enabled")
    if any(state["cmp_phase_stimulus"]):
        raise AssertionError(f"{label}: phantom BEMF phase stimulus")
    # No normal native positive drive is permitted absent reviewed
    # board definitions and actual command waveform.
    print(f"G13B0_{label}_NO_NATIVE_DRIVE=PASS "
          f"tick={state['firmware']['tick']} "
          f"throt={state['firmware']['throt']} "
          f"PB13_DOE=0x{state['pb13_gpio_doe']:08x} "
          f"PB13_PINCM=0x{state['pb13_mapped']:08x} "
          f"TBCLKSYNC=0x{state['tbclksync']:08x} "
          f"PWM_OBS=0x{state['pwm_observer_status']:08x}", flush=True)


def test_no_command(args):
    elf = args.elf.resolve()
    qemu = args.qemu.resolve()
    wfi = native_wfi_locations(elf, args.objdump)
    # Original Rel17 has multiple real WFI instructions. The first
    # one was independently shown by G12 to be reached/revisited with
    # no command; do not invent a different main loop milestone.
    wfi_pc = wfi[0]
    native_symbols = {name: symbol_address(elf, name, args.nm)
                      for name in ("throt", "tick")}
    with tempfile.TemporaryDirectory(prefix="g13b0-native-") as td:
        sock = str(Path(td) / "gdb.sock")
        cmd = [str(qemu), "-M", "am13e23019,esc-sim=on",
               "-kernel", str(elf), "-display", "none",
               "-monitor", "none", "-serial", "none",
               "-S", "-chardev",
               f"socket,path={sock},server=on,wait=off,id=gdb0",
               "-gdb", "chardev:gdb0",
               "-icount", "shift=2,sleep=off,align=off"]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True)
        samples = []
        try:
            with wait_for_socket(sock, proc) as conn:
                rsp = RSP(conn)
                if not rsp.command("?").startswith(("S", "T")):
                    raise RuntimeError("G13B0 QEMU not halted at reset")
                if "qXfer:features:read+" not in rsp.command(
                        "qSupported:qXfer:features:read+"):
                    raise RuntimeError("G13B0 needs target XML")
                if not rsp.command(
                        "qXfer:features:read:target.xml:0,1").startswith(("m<", "l<")):
                    raise RuntimeError("G13B0 target XML unavailable")
                if rsp.command("Qqemu.sstep:1") != "OK":
                    raise RuntimeError("QEMU timed step is required")
                _release, hardfault, count = reach_release(
                    rsp, elf, args.startup_steps)
                pre = snapshot(rsp, native_symbols)
                if pre["arch"]["primask"] != 1 or pre["arch"]["ipsr"] != 0:
                    raise AssertionError("Not at original masked IRQ barrier")
                # Initial peripheral safety must already be fail-closed.
                if pre["pb13_gpio_doe"] & GATE_EN or pre["qualified_by_gate_and_pwm_pins"]:
                    raise AssertionError("Native reference armed before CPSIE")
                print("G13B0_NATIVE_PRE_CPSIE_GATE_AND_PADS_ISOLATED=PASS",
                      flush=True)
                armed = {wfi_pc, hardfault}
                for pc in armed:
                    add_bp(rsp, pc)
                try:
                    for n in range(2):
                        stop, interrupted = continue_bounded(rsp, args.slice_ms)
                        if interrupted:
                            raise AssertionError(
                                f"Native main WFI not reached within "
                                f"bounded run #{n} (not a PASS)")
                        if not stop.startswith(("S05", "T05")):
                            raise RuntimeError(f"Unexpected GDB stop: {stop}")
                        pc = rsp.reg(15)
                        if pc == hardfault:
                            raise AssertionError(
                                "Native firmware HardFault before no-drive proof")
                        if pc != wfi_pc:
                            raise AssertionError(f"Unexpected stop 0x{pc:08x}")
                        state = snapshot(rsp, native_symbols)
                        require_no_native_drive(state, f"WFI_{n}")
                        samples.append(state)
                        if n == 0:
                            del_bp(rsp, wfi_pc)
                            armed.remove(wfi_pc)
                            result = rsp.command("s")  # genuine WFI
                            if not result.startswith(("S05", "T05")):
                                raise RuntimeError("WFI not stepped")
                            if rsp.reg(15) == wfi_pc:
                                raise AssertionError("GDB did not advance past WFI")
                            add_bp(rsp, wfi_pc)
                            armed.add(wfi_pc)
                finally:
                    for pc in sorted(armed, reverse=True):
                        del_bp(rsp, pc)
        finally:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            if proc.stderr:
                if proc.returncode not in (0, -15):
                    stderr = proc.stderr.read()
                    if stderr:
                        print("G13B0_QEMU_STDERR " + stderr[-3000:])
                proc.stderr.close()
    if samples[1]["firmware"]["tick"] <= samples[0]["firmware"]["tick"]:
        raise AssertionError("G13B0 tick did not increase during repeated WFI")
    print("PASS_G13B0_ORIGINAL_ELF_NO_COMMAND_NO_DRIVE_TWO_WFI "
          "NOT_NATIVE_CLOSED_LOOP", flush=True)
    if args.artifact:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(samples, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", required=True, type=Path)
    p.add_argument("--elf", required=True, type=Path)
    p.add_argument("--objdump", default="arm-none-eabi-objdump")
    p.add_argument("--nm", default="arm-none-eabi-nm")
    p.add_argument("--startup-steps", type=int, default=32768)
    p.add_argument("--slice-ms", type=int, default=100)
    p.add_argument("--artifact", type=Path)
    args = p.parse_args()
    if not args.elf.is_file() or not args.qemu.is_file():
        p.error("Original native ELF and compiled QEMU required")
    if not 10 <= args.slice_ms <= 1000:
        p.error("Bounded slice should be 10..1000 ms")
    app_vector_from_elf(args.elf)
    test_no_command(args)


if __name__ == "__main__":
    main()
