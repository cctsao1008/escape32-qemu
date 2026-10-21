#!/usr/bin/env python3
"""G13B2A original-ELF SIM_ONLY safety preflight and first MMIO blocker.

The board profile is opt-in and its GPIO/gate/deadtime/OC values are
explicitly fictional simulation assumptions. No output, SRAM, IRQ or
register state is modified by this probe: QEMU GDB RSP single-step
and temporary SDK-return breakpoints execute real original guest code.

The proof is intentionally *negative*: until the native firmware and
the simulator have genuinely functional independent PA22 nFAULT and
three-phase asynchronous OC/TZ interlocks, nobody may call this
an arming/motor-output PASS.
"""
import argparse
import collections
import json
import socket
import subprocess
import tempfile
from pathlib import Path

from elf_image import APP_BASE, app_vector_from_elf, elf_function_address
from g1_handoff import (
    RSP, wait_for_socket, fast_forward_sdk_delay
)
from g11_exception_lifecycle import observer
from g12_runtime_progress import inspect_hardfault
from tools.virtual_bldc import GPIO1_BASE, PINCM_BASE, MCPWM4_ROUTES, GATE_EN

SYST = 0xe000ed28
BFAR = 0xe000ed38
PWM4_BASE = 0x40014000
TBCLKSYNC = 0x400b048c
PWM_OBS = 0x5ffe1000

# Known missing *independent safety* peripheral regions in G13A/B1:
# no generic "MMIO OK" bit or simulator-forced safety-ready state.
INDEPENDENT_PROTECTION_RANGES = (
    (0x40461000, 0x40464000, "CMPSS1/2/3 independent overcurrent"),
    (0x40468000, 0x40469000, "INPUTXBAR PA22 fault routing"),
    (0x40469000, 0x4046a000, "PWMXBAR OC/Trip routing")
)


def connected_or_active(rsp):
    # Active-high PB13 is an explicitly declared SIM_ONLY assumption,
    # never a Quanta hardware polarity fact.
    doe = rsp.mem32(GPIO1_BASE + 0x12c0)
    dout = rsp.mem32(GPIO1_BASE + 0x1280)
    pb13 = rsp.mem32(PINCM_BASE + 4 * 45)
    pads = [rsp.mem32(PINCM_BASE + 4 * pin) for pin, _ in MCPWM4_ROUTES]
    tbclk = rsp.mem32(TBCLKSYNC)
    obs = rsp.mem32(PWM_OBS)
    is_gate_active = bool((doe & GATE_EN) and (dout & GATE_EN) and
                          (pb13 & 0x3f) == 1)
    return dict(
        gate_output_enable=bool(doe & GATE_EN),
        gate_output_high=bool(dout & GATE_EN),
        gate_pincm=pb13,
        gate_active=is_gate_active,
        pwm_pincm=pads,
        pwm_pads_connected=any(
            ((v & 0xBF) != 0x81) for v in pads),
        tbclksync=tbclk,
        pwm_observer=obs,
        pwm_running=bool(obs & 1),
    )


def preflight(args):
    elf = args.elf.resolve()
    app_vector_from_elf(elf)
    delay_pc, length = elf_function_address(elf, "DL_Common_delayCycles")
    if length != 10:
        raise RuntimeError("Native SDK delay function changed; stop")
    sdk_loop = (delay_pc + 2, delay_pc + 4, delay_pc + 6)
    hardfault_pc = None
    report = {}
    with tempfile.TemporaryDirectory(prefix="g13b2a-sim-only-") as temp:
        sock = str(Path(temp) / "gdb.sock")
        cmd = [str(args.qemu.resolve()), "-M",
               "am13e23019,esc-sim=on,esc-sim-nfault-asserted=" +
               ("on" if args.nfault_asserted else "off"),
               "-kernel", str(elf), "-display", "none",
               "-serial", "none", "-monitor", "none", "-S",
               "-chardev", f"socket,path={sock},server=on,wait=off,id=gdb0",
               "-gdb", "chardev:gdb0",
               "-icount", "shift=2,sleep=off,align=off"]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            with wait_for_socket(sock, proc) as conn:
                rsp = RSP(conn)
                if not rsp.command("?").startswith(("S", "T")):
                    raise RuntimeError("No stopped native CPU")
                if "qXfer:features:read+" not in rsp.command(
                        "qSupported:qXfer:features:read+"):
                    raise RuntimeError("Missing target CPU description")
                if not rsp.command(
                        "qXfer:features:read:target.xml:0,1").startswith(("m<", "l<")):
                    raise RuntimeError("Cannot read target CPU description")
                if rsp.command("Qqemu.sstep:1") != "OK":
                    raise RuntimeError("No virtual clock IRQ steps")
                hardfault_pc = rsp.mem32(APP_BASE + 12) & ~1
                end_reason = "step-limit"
                history = collections.deque(maxlen=8)
                for i in range(args.steps):
                    stop = rsp.command("s")
                    if not stop.startswith(("S05", "T05")):
                        raise RuntimeError(f"Unexpected guest execution stop {stop!r}")
                    pc = rsp.reg(15)
                    if pc in sdk_loop:
                        pc = fast_forward_sdk_delay(
                            rsp, pc, hardfault_pc, sdk_loop)
                    history.append(pc)
                    if pc == hardfault_pc:
                        end_reason = "hardfault"
                        break
                state = observer(rsp)
                pad = connected_or_active(rsp)
                cfsr = rsp.mem32(SYST)
                bfar = rsp.mem32(BFAR)
                report = {
                    "reason": end_reason, "steps": i + 1,
                    "pc": state["pc"], "ipsr": state["ipsr"],
                    "cfsr": cfsr, "bfar": bfar,
                    "pads": pad, "history": list(history),
                    "nfault_fixture_asserted": args.nfault_asserted
                }
                print("G13B2A_NATIVE_SAFETY_SNAPSHOT " +
                      json.dumps(report, sort_keys=True), flush=True)
                if end_reason == "hardfault":
                    inspect_hardfault(rsp, elf, args.objdump)
                if (pad["gate_active"] or pad["pwm_pads_connected"] or
                        pad["pwm_running"] or (pad["tbclksync"] & 1)):
                    raise AssertionError(
                        "G13B2A unexpected physical drive BEFORE "
                        "independent protection MMIO qualification")
                print("PASS_G13B2A_SIM_ONLY_UNQUALIFIED_DRIVE_REMAINS_OFF",
                      flush=True)
                if end_reason == "hardfault":
                    kind = next((desc for lo, hi, desc in
                                 INDEPENDENT_PROTECTION_RANGES
                                 if lo <= bfar < hi), "UNKNOWN_MMIO")
                    print(f"G13B2A_NATIVE_BOOT_STOP reason={kind} "
                          f"BFAR=0x{bfar:08x} CFSR=0x{cfsr:08x} "
                          "PROTECTION_MODEL_NOT_YET_QUALIFIED", flush=True)
                    # Not a positive boot/arming result. Neither silently
                    # ignore nor declare exception model ready.
                else:
                    print("G13B2A_NATIVE_BOOT_STOP bounded-no-fault; "
                          "no positive output authorization proven",
                          flush=True)
        finally:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            if proc.stderr:
                stderr = proc.stderr.read()
                if stderr:
                    print("G13B2A_QEMU_STDERR " + stderr[-1600:])
                proc.stderr.close()
    if args.artifact:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(report, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", required=True, type=Path)
    p.add_argument("--elf", required=True, type=Path)
    p.add_argument("--objdump", default="arm-none-eabi-objdump")
    p.add_argument("--steps", type=int, default=32768)
    p.add_argument("--nfault-asserted", action="store_true")
    p.add_argument("--artifact", type=Path)
    args = p.parse_args()
    if not args.qemu.is_file() or not args.elf.is_file():
        p.error("Missing SIM_ONLY native ELF / QEMU")
    if not 100 <= args.steps <= 32768:
        p.error("Steps must be bounded [100..32768]")
    preflight(args)


if __name__ == "__main__":
    main()
