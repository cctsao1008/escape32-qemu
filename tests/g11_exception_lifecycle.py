#!/usr/bin/env python3
"""G11B-D Cortex-M33 exception lifecycle investigation against an ORIGINAL ELF.

No source/binary patching. Two independent QEMU guests reach the verified
CPSIE i in the firmware, then compare timer-enabled GDB single-stepping with
continuous execution at *that same instruction*. QEMU's own CPU_LOG_INT log
records exception return/integrity decisions without rewriting CPU helpers.

PASS only indicates reproducible non-invasive instrumentation; an observed
INVPC is an OPEN firmware/QEMU/interrupt interaction, never boot success.
"""
import argparse
import collections
import os
import socket
import subprocess
import tempfile
from pathlib import Path

from elf_image import APP_BASE, app_vector_from_elf, elf_function_address
from g1_handoff import RSP, wait_for_socket, fast_forward_sdk_delay

OBS = 0x5ffe3000
SCB_ICSR = 0xe000ed04
SCB_SHCSR = 0xe000ed24
SCB_CFSR = 0xe000ed28
SCB_HFSR = 0xe000ed2c

def observer(rsp):
    # Eleven contiguous read-only observer registers: one coherent RSP
    # memory packet. Core/SCB cross-checks below remain independent.
    values = rsp.mem32_block(OBS, 11)
    if values[0] != 0x47313101:
        raise AssertionError("Missing G11 state observer or outdated QEMU")
    names = ("magic", "primask", "basepri", "faultmask", "control",
             "msp", "psp", "ipsr", "lr", "pc", "xpsr")
    data = dict(zip(names, values))
    # SCB.SHCSR/CFSR/HFSR are adjacent 32-bit architectural registers.
    # Read all three in one checked RSP packet at the SAME stopped state.
    # Preserve a separate ICSR sample and independent core-register checks.
    icsr = rsp.mem32(SCB_ICSR)
    shcsr, cfsr, hfsr = rsp.mem32_block(SCB_SHCSR, 3)
    data.update({"icsr": icsr, "shcsr": shcsr,
                 "cfsr": cfsr, "hfsr": hfsr})
    # Ensure observer is passive and agrees with the public GDB core view.
    if ((rsp.reg(25) & 0x1ff) != data["ipsr"] or
            rsp.reg(13) != (data["psp"] if
                            not data["ipsr"] and data["control"] & 2
                            else data["msp"]) or
            rsp.reg(15) != data["pc"]):
        raise AssertionError("G11 observer disagrees with GDB core registers")
    return data

def display(mode, event, state):
    print(f"G11_{mode}_{event} PC=0x{state['pc']:08x} "
          f"LR=0x{state['lr']:08x} IPSR={state['ipsr']} "
          f"PRIMASK={state['primask']} BASEPRI={state['basepri']} "
          f"FAULTMASK={state['faultmask']} "
          f"CONTROL=0x{state['control']:08x} "
          f"MSP=0x{state['msp']:08x} PSP=0x{state['psp']:08x} "
          f"ICSR=0x{state['icsr']:08x} "
          f"CFSR=0x{state['cfsr']:08x} HFSR=0x{state['hfsr']:08x}",
          flush=True)

def resolve_cpsie(rsp, elf):
    start, size = elf_function_address(
        elf, "am13e_app_motor_runtime_enable_interrupts")
    if not 12 <= size <= 4096:
        raise RuntimeError(f"Unexpected release barrier size={size}")
    pcs = [start + off for off in range(0, size - 1, 2)
           if rsp.mem16(start + off) == 0xb662]
    if len(pcs) != 1:
        raise RuntimeError(f"Expected one CPSIE i in native barrier, got: {pcs}")
    print(f"G11_NATIVE_RELEASE_FUNCTION=0x{start:08x} "
          f"SIZE={size} CPSIE_I=0x{pcs[0]:08x} ORIGINAL_ELF")
    return pcs[0]

def reach_release(rsp, elf, limit):
    delay_start, delay_size = elf_function_address(elf, "DL_Common_delayCycles")
    if delay_size != 10:
        raise RuntimeError("SDK delay function changed; cannot fast-forward")
    delay_loop = (delay_start + 2, delay_start + 4, delay_start + 6)
    hardfault = rsp.mem32(APP_BASE + 12) & ~1
    cpsie = resolve_cpsie(rsp, elf)
    nff = 0
    current = rsp.reg(15)
    for step in range(1, limit + 1):
        if current == cpsie:
            print(f"G11_REACHED_RELEASE step={step} "
                  f"SDK_DELAY_CONTINUES={nff} BEFORE_CPSIE")
            return cpsie, hardfault, step
        if current == hardfault:
            raise AssertionError(f"HardFault before native CPSIE at step={step}")
        stopped = rsp.command("s")
        if not stopped.startswith(("S05", "T05")):
            raise RuntimeError(f"Unexpected step stop: {stopped}")
        current = rsp.reg(15)
        if current in delay_loop:
            current = fast_forward_sdk_delay(rsp, current, hardfault, delay_loop)
            nff += 1
    raise AssertionError(f"Native CPSIE i not reached in {limit} GDB observations")

def add_bp(rsp, address):
    if rsp.command(f"Z0,{address:x},2") != "OK":
        raise RuntimeError(f"Failed to install breakpoint 0x{address:08x}")

def del_bp(rsp, address):
    if rsp.command(f"z0,{address:x},2") != "OK":
        raise RuntimeError(f"Failed to remove breakpoint 0x{address:08x}")

def stepped(rsp, cpsie, hardfault, count):
    pre = observer(rsp)
    display("STEP", "PRE_CPSIE", pre)
    if pre["primask"] != 1 or pre["ipsr"] != 0:
        raise AssertionError("Native barrier is not in masked Thread mode")
    seq = []
    last_ipsr = pre["ipsr"]
    for n in range(1, count + 1):
        stop = rsp.command("s")
        if not stop.startswith(("S05", "T05")):
            raise RuntimeError(f"G11 single-step unexpected reply: {stop}")
        state = observer(rsp)
        if n <= 12 or state["ipsr"] != last_ipsr or state["pc"] == hardfault:
            display("STEP", f"EVENT_{n}", state)
        if state["ipsr"] != last_ipsr:
            seq.append((n, state["ipsr"], state["pc"], state["lr"]))
        last_ipsr = state["ipsr"]
        if state["pc"] == hardfault:
            break
    final = observer(rsp)
    print(f"G11_STEP_SUMMARY events={len(seq)} "
          f"exceptions={seq[:24]} "
          f"REACHED_HARDFAULT={int(final['pc']==hardfault)} "
          f"INVPC={int(bool(final['cfsr'] & 0x40000))}")
    if final["primask"] != 0 and not (final["cfsr"] & 0x40000):
        raise AssertionError("CPSIE did not release PRIMASK")
    return final

def receive_async_stop(rsp):
    """Receive QEMU's asynchronous stop after GDB Ctrl-C on a running 'c'.

    RSP.command('c') already consumed its initial '+' ACK before timing
    out waiting for the stop packet. It is INCORRECT to send a new GDB
    command at that point: a pending '$T02' will be misread as its ACK.
    """
    start = rsp.byte()
    if start == b"+":   # tolerate an already outstanding continue ACK
        start = rsp.byte()
    if start != b"$":
        raise RuntimeError(f"Expected async GDB stop packet, got {start!r}")
    packet = bytearray()
    while True:
        ch = rsp.byte()
        if ch == b"#":
            break
        packet.extend(ch)
    checksum = (rsp.byte() + rsp.byte()).decode("ascii")
    if checksum.lower() != f"{sum(packet) & 255:02x}":
        rsp.sock.sendall(b"-")
        raise RuntimeError("Bad asynchronous GDB stop checksum")
    rsp.sock.sendall(b"+")
    return packet.decode("ascii")

def continue_bounded(rsp, milliseconds):
    """Run genuine guest instructions; interrupt and HALT after deadline."""
    timeout = rsp.sock.gettimeout()
    try:
        rsp.sock.settimeout(milliseconds / 1000.0)
        try:
            return rsp.command("c"), False
        except socket.timeout:
            rsp.sock.settimeout(5)
            rsp.sock.sendall(b"\x03")  # GDB remote asynchronous interrupt
            stopped = receive_async_stop(rsp)
            if not stopped.startswith(("S02", "T02", "S05", "T05")):
                raise RuntimeError(f"Unexpected async stop: {stopped}")
            return stopped, True
    finally:
        rsp.sock.settimeout(timeout)

def continuous(rsp, cpsie, hardfault, elf, count, slice_ms):
    pre = observer(rsp)
    display("CONT", "PRE_CPSIE", pre)
    if pre["primask"] != 1 or pre["ipsr"] != 0:
        raise AssertionError("Native barrier is not in masked Thread mode")
    systick = elf_function_address(elf, "SysTick_Handler")[0]
    pendsv = elf_function_address(elf, "PendSV_Handler")[0]
    entry = {systick: "SYSTICK_ENTRY", pendsv: "PENDSV_ENTRY",
             hardfault: "HARDFAULT_ENTRY", cpsie+2: "THREAD_AFTER_CPSIE"}
    armed = list(dict.fromkeys(entry))
    for bp in armed:
        add_bp(rsp, bp)
    seen = []
    final = pre
    try:
        for i in range(count):
            stopped, interrupted = continue_bounded(rsp, slice_ms)
            if not interrupted and not stopped.startswith(("S05", "T05")):
                raise RuntimeError(f"Unexpected continue stop: {stopped}")
            final = observer(rsp)
            at = final["pc"]
            label = ("BOUNDED_CONT_RUN_PAUSED" if interrupted else
                     entry.get(at, f"UNEXPECTED_PC_0x{at:08x}"))
            display("CONT", f"STOP_{i}_{label}", final)
            seen.append(label)
            if interrupted:
                print(f"G11_CONT_BOUNDED_RUN slice_ms={slice_ms} "
                      "QEMU_STOPPED_BY_GDB_CTRL_C GUEST_INSTRUCTIONS_EXECUTED")
                break
            if at == hardfault:
                break
            if at in armed:
                del_bp(rsp, at)
                armed.remove(at)
            if at not in entry:
                break
            if "THREAD_AFTER_CPSIE" in seen and "SYSTICK_ENTRY" in seen:
                break
        print(f"G11_CONT_SUMMARY stops={seen} "
              f"REACHED_HARDFAULT={int(final['pc']==hardfault)} "
              f"INVPC={int(bool(final['cfsr'] & 0x40000))}")
    finally:
        for bp in reversed(armed):
            del_bp(rsp, bp)
    return final

def log_summary(mode, logpath, savedir):
    if not logpath.exists():
        print(f"G11_{mode}_QEMU_CPU_LOG_UNAVAILABLE")
        return
    # Preserve full CPU-side evidence, not only the final fault snapshot.
    content = logpath.read_text(errors="replace")
    if savedir:
        (savedir / f"g11-{mode}-cpu-exceptions.log").write_text(content)
    relevant = [s for s in content.splitlines()
                if ("Exception return:" in s or
                    "taking UsageFault" in s or
                    "taking HardFault" in s or
                    "exception return" in s.lower() or
                    "Taking exception" in s)]
    counts = collections.Counter()
    for entry in relevant:
        if "Exception return:" in entry:
            counts["returns"] += 1
        if "integrity check" in entry:
            counts["integrity_failure"] += 1
        if "taking UsageFault" in entry:
            counts["usagefault"] += 1
    print(f"G11_{mode}_QEMU_CPU_INT_EVENT_COUNTS {dict(counts)} "
          f"TOTAL_MATCHES={len(relevant)} LOG_BYTES={len(content)}")
    for line in relevant[-20:]:
        print(f"G11_{mode}_CPU_INT {line[:260]}")

def run(mode, qemu, elf, args, savedir):
    with tempfile.TemporaryDirectory(prefix=f"am13e-g11-{mode}-") as td:
        folder = Path(td)
        sockpath = folder / "gdb.sock"
        cpulog = folder / "cpu-int.log"
        cmd = [str(qemu), "-M", "am13e23019,esc-sim=on",
               "-kernel", str(elf), "-display", "none",
               "-monitor", "none", "-serial", "none",
               "-S", "-chardev",
               f"socket,path={sockpath},server=on,wait=off,id=gdb0",
               "-gdb", "chardev:gdb0",
               "-icount", "shift=10,sleep=off,align=off",
               "-d", "int", "-D", str(cpulog)]
        process = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            with wait_for_socket(str(sockpath), process) as conn:
                rsp = RSP(conn)
                if not rsp.command("?").startswith(("S", "T")):
                    raise RuntimeError("QEMU not halted at reset")
                supported = rsp.command("qSupported:qXfer:features:read+")
                if "qXfer:features:read+" not in supported:
                    raise RuntimeError("Missing QEMU target XML")
                if not rsp.command("qXfer:features:read:target.xml:0,1").startswith(("m<","l<")):
                    raise RuntimeError("Cannot initialize QEMU GDB register layout")
                if rsp.command("Qqemu.sstep:1") != "OK":
                    raise RuntimeError("QEMU timed IRQ single-step enable failed")
                cpsie, hardfault, scans = reach_release(rsp, elf, args.startup_steps)
                if mode == "step":
                    return stepped(rsp, cpsie, hardfault, args.post_steps)
                return continuous(rsp, cpsie, hardfault, elf,
                                  args.cont_stops, args.cont_slice_ms)
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log_summary(mode.upper(), cpulog, savedir)
            process.stderr.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", required=True, type=Path)
    ap.add_argument("--elf", required=True, type=Path)
    ap.add_argument("--mode", choices=("step", "continuous", "both"),
                    default="both")
    ap.add_argument("--startup-steps", type=int, default=32768)
    ap.add_argument("--post-steps", type=int, default=512)
    ap.add_argument("--cont-stops", type=int, default=6)
    ap.add_argument("--cont-slice-ms", type=int, default=60,
                    help="Bound each continuous GDB slice before Ctrl-C")
    ap.add_argument("--artifact-dir", type=Path)
    ap.add_argument("--require-no-invpc", action="store_true",
                    help="Regression gate: neither run may set sticky CFSR.INVPC")
    args = ap.parse_args()
    for path in (args.qemu, args.elf):
        if not path.is_file():
            ap.error("Missing file: " + str(path))
    if not (1 <= args.startup_steps <= 65536 and
            1 <= args.post_steps <= 4096 and 1 <= args.cont_stops <= 20 and
            10 <= args.cont_slice_ms <= 1000):
        ap.error("Invalid bound")
    app_vector_from_elf(args.elf)
    savedir = args.artifact_dir
    if savedir:
        savedir.mkdir(parents=True, exist_ok=True)
    results = {}
    modes = ("step", "continuous") if args.mode == "both" else (args.mode,)
    for mode in modes:
        results[mode] = run(mode, args.qemu.resolve(), args.elf.resolve(),
                            args, savedir)
    if len(results) == 2:
        a, b = results["step"], results["continuous"]
        print(f"G11_COMPARISON STEP_INVPC={int(bool(a['cfsr'] & 0x40000))} "
              f"CONT_INVPC={int(bool(b['cfsr'] & 0x40000))} "
              f"STEP_IPSR={a['ipsr']} CONT_IPSR={b['ipsr']}")
    if args.require_no_invpc:
        # CFSR is sticky unless guest code clears it. Both runs stop
        # immediately after the native firmware IRQ release, and a
        # regression must fail CI rather than be misreported as PASS.
        for mode, state in results.items():
            if state["cfsr"] & 0x00040000:
                raise AssertionError(f"INVPC recurred during {mode} "
                                     "exception lifecycle observation")
        print("PASS_G11_NATIVE_CPSIE_SYSTICK_NO_INVPC_BOUNDED_TRACE")
    print("PASS_G11_DIAGNOSTIC_INSTRUMENTATION_ONLY "
          "NO_FIRMWARE_BOOT_OR_EXCEPTION_RETURN_CORRECTNESS_CLAIM")

if __name__ == "__main__":
    main()
