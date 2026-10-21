#!/usr/bin/env python3
"""G13B2D: original SIM_ONLY firmware handles *physical* independent faults.

An opt-in, fictional TEST-ONLY board boots the original ELF and configures
its own CMPSS1/2/3 -> PWMXBAR OST3 and PA22 -> INPUTXBAR OST2 routes.
QTest touches ONLY external analog samples or external nFAULT level.
QEMU hardware (not a guest/host status write) must latch the correct OST,
assert the genuine MCPWM4 interrupt and enter the original native ISR.
The native ISR must reach its own shutdown function. No gate, PWM, DMA,
CPU state, IRQ bit or other firmware register is externally authored.
This is a negative safety test, not valid arming or closed-loop evidence.
"""
import argparse
import json
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elf_image import app_vector_from_elf, elf_function_address
from g0_memory import QTest
from g1_handoff import RSP, wait_for_socket
from g11_exception_lifecycle import (
    reach_release, observer, add_bp, del_bp, continue_bounded
)
from g12_runtime_progress import native_wfi_locations
from g13b_native_wfi import wait_for_native_main_wfi
from g13b_native_no_drive import symbol_address
from g13b2_native_safety import snapshot, verify, EXT_OC, PWM4

FAULT_TYPES = {
    "nfault": (0x18, 1, 0x20000, 2),
    "oc-w": (0x00, 0x10000 | 3000, 0x40000, 4),
    "oc-v": (0x04, 0x10000 | 3000, 0x40000, 4),
    "oc-u": (0x08, 0x10000 | 3000, 0x40000, 4),
}


def run(args):
    app_vector_from_elf(args.elf)
    wfi = native_wfi_locations(args.elf, args.objdump)
    throt = symbol_address(args.elf, "throt")
    irq_pc = elf_function_address(args.elf, "MCPWM4_IRQHandler")[0]
    shutdown_pc = elf_function_address(
        args.elf, "am13e_app_motor_fault_shutdown")[0]
    offset, level, trip_mask, ext_flag = FAULT_TYPES[args.fault]
    assert shutdown_pc != irq_pc

    with tempfile.TemporaryDirectory(prefix="g13b2d-native-") as tmp:
        qtpath = str(Path(tmp) / "qtest.sock")
        gdbpath = str(Path(tmp) / "gdb.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(qtpath)
            listener.listen(1)
            listener.settimeout(15)
            proc = subprocess.Popen(
                [str(args.qemu.resolve()), "-M",
                 "am13e23019,esc-sim=on,esc-sim-nfault-asserted=off",
                 "-kernel", str(args.elf.resolve()),
                 "-S", "-display", "none", "-serial", "none",
                 "-monitor", "none",
                 "-chardev",
                 f"socket,path={gdbpath},server=on,wait=off,id=gdb0",
                 "-gdb", "chardev:gdb0",
                 "-qtest", f"unix:path={qtpath}",
                 "-icount", "shift=2,sleep=off,align=off"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            qtconn = None
            armed = set()
            evidence = {}
            try:
                qtconn, _ = listener.accept()
                q = QTest(qtconn)
                # Physical current samples below the hypothetical DAC
                # threshold, supplied *before* native CPU runs.
                for i in range(3):
                    q.write(EXT_OC + 4 * i, 0x10000 | 1000)
                with wait_for_socket(gdbpath, proc) as conn:
                    rsp = RSP(conn)
                    if not rsp.command("?").startswith(("S", "T")):
                        raise RuntimeError("G13B2D no halted native CPU")
                    if "qXfer:features:read+" not in rsp.command(
                            "qSupported:qXfer:features:read+"):
                        raise RuntimeError("Missing target CPU layout")
                    if not rsp.command(
                            "qXfer:features:read:target.xml:0,1").startswith(
                            ("m<", "l<")):
                        raise RuntimeError("No target CPU XML")
                    if rsp.command("Qqemu.sstep:1") != "OK":
                        raise RuntimeError("QEMU virtual-time stepping unavailable")
                    _, hardfault, _ = reach_release(
                        rsp, args.elf, args.startup_steps)
                    armed = {*wfi, hardfault}
                    for address in sorted(armed):
                        add_bp(rsp, address)
                    try:
                        hit_wfi = wait_for_native_main_wfi(
                            rsp, wfi, hardfault, args.slice_ms,
                            args.runtime_slices,
                            stage=f"B2D_{args.fault.upper()}_NEUTRAL")
                        baseline = snapshot(rsp, throt)
                        verify(baseline)
                        if baseline["tzflags"] != 0:
                            raise AssertionError("Neutral baseline already tripped")
                        # Retire WFI breakpoints before resuming the CPU;
                        # a WFI is the rendezvous, not evidence of handling.
                        for address in wfi:
                            del_bp(rsp, address)
                            armed.remove(address)
                        for address in (irq_pc, shutdown_pc):
                            add_bp(rsp, address)
                            armed.add(address)

                        # Only an external PHYSICAL condition changes.
                        # No write to PWM4, XBAR, CMPSS or guest memory.
                        q.write(EXT_OC + offset, level)
                        raw = q.read(EXT_OC + 0x10)
                        tz = q.read(PWM4 + 0xb0)
                        intflg = q.read(PWM4 + 0x94)
                        instant = snapshot(rsp, throt)
                        evidence.update(
                            fault=args.fault, native_wfi=hit_wfi,
                            physical_source_levels=raw, tzflags=tz,
                            interrupt_flags=intflg,
                            irq_vector_pc=irq_pc,
                            shutdown_pc=shutdown_pc,
                            gate_inactive=(instant["pb13_dout"] == 0),
                            pwm_disabled=not bool(instant["pwm_running"]),
                            native_throttle=instant["throt"])
                        print("G13B2D_HARDWARE_LATCH_BEFORE_GUEST_CPU " +
                              json.dumps(evidence, sort_keys=True), flush=True)
                        if ((raw & ext_flag) != ext_flag or
                                (tz & trip_mask) != trip_mask or
                                not (intflg & 0x04) or
                                instant["pb13_dout"] or
                                instant["cfsr"] or instant["hfsr"]):
                            raise AssertionError(
                                "External fault did not generate real latched "
                                "MCPWM4 OST+INT while halted")
                        print("PASS_G13B2D_PHYSICAL_FAULT_TO_OST_WHILE_CPU_HALTED",
                              flush=True)

                        stop, interrupted = continue_bounded(
                            rsp, args.slice_ms)
                        if interrupted or not stop.startswith(("S05", "T05")):
                            raise AssertionError(
                                "Native MCPWM4 IRQ not dispatched for "
                                f"actual physical {args.fault} fault")
                        pc = rsp.reg(15)
                        if pc != irq_pc:
                            raise AssertionError(
                                f"Expected actual original ISR 0x{irq_pc:08x}, "
                                f"got PC=0x{pc:08x} (hardfault/shutdown?)")
                        exception = observer(rsp)
                        evidence["irq_ipsr"] = exception["ipsr"]
                        if exception["ipsr"] != 44:
                            raise AssertionError(
                                f"Not genuine MCPWM4 exception: "
                                f"IPSR={exception['ipsr']}")
                        print("PASS_G13B2D_ORIGINAL_ELF_MCPWM4_IRQ_ENTRY "
                              f"fault={args.fault} ipsr=44", flush=True)

                        del_bp(rsp, irq_pc)
                        armed.remove(irq_pc)
                        stop, interrupted = continue_bounded(
                            rsp, args.slice_ms)
                        if interrupted or not stop.startswith(("S05", "T05")):
                            raise AssertionError(
                                "Original native MCPWM4 ISR never reached "
                                "its own motor fault shutdown")
                        pc = rsp.reg(15)
                        if pc != shutdown_pc:
                            raise AssertionError(
                                f"Unexpected PC 0x{pc:08x}; expected "
                                f"native fault_shutdown 0x{shutdown_pc:08x}")
                        current = snapshot(rsp, throt)
                        if (current["pb13_dout"] or
                                current["cfsr"] or current["hfsr"] or
                                not (current["tzflags"] & trip_mask)):
                            raise AssertionError(
                                "Native shutdown entry lost physical "
                                "Trip latch or gate became active")
                        evidence["shutdown_pc_hit"] = pc
                        evidence["shutdown_ipsr"] = observer(rsp)["ipsr"]
                        print("PASS_G13B2D_ORIGINAL_ELF_FAULT_ISR_REACHES_SHUTDOWN "
                              f"fault={args.fault} "
                              "NOT_NATIVE_MOTOR_START", flush=True)
                    finally:
                        for address in sorted(armed, reverse=True):
                            del_bp(rsp, address)
            finally:
                if qtconn is not None:
                    qtconn.close()
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                if proc.stderr:
                    if proc.returncode not in (0, -15):
                        print("G13B2D_QEMU_STDERR " +
                              proc.stderr.read()[-2500:])
                    proc.stderr.close()
    if args.artifact:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(evidence, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    p.add_argument("--fault", required=True, choices=sorted(FAULT_TYPES))
    p.add_argument("--objdump", default="arm-none-eabi-objdump")
    p.add_argument("--startup-steps", type=int, default=32768)
    p.add_argument("--slice-ms", type=int, default=150)
    p.add_argument("--runtime-slices", type=int, default=12)
    p.add_argument("--artifact", type=Path)
    args = p.parse_args()
    if not args.qemu.is_file() or not args.elf.is_file():
        p.error("Missing compiled QEMU or genuine SIM_ONLY ELF")
    run(args)


if __name__ == "__main__":
    main()
