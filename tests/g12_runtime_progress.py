#!/usr/bin/env python3
"""G12: measure ORIGINAL ESCape32 runtime progress across QEMU icount scales.

Native ELF is never edited. This is a *measurement* and no physical MCU
timing model is implied by QEMU's instruction-count virtual nanoseconds.

Two (or more) independent QEMU processes are stepped to the exact native
CPSIE i via verified SDK delay execution. Then real guest execution
continues with bounded GDB breakpoints on SysTick, PendSV, post-CPSIE
Thread, and actual WFI instructions within am13e_rel17_app_main.
No MMIO/CPU/IRQ registers are patched and no fabricated BEMF is injected.
"""
import argparse
import collections
import json
import re
import subprocess
import tempfile
from pathlib import Path

from elf_image import app_vector_from_elf, elf_function_address
from g1_handoff import RSP, wait_for_socket
from g11_exception_lifecycle import (
    add_bp, del_bp, continue_bounded, observer, reach_release
)

SYST_CSR = 0xe000e010
SYST_RVR = 0xe000e014
SCB_SCR = 0xe000ed10
CFSR_INVPC = 0x40000
SCB_BFAR = 0xe000ed38


def inspect_hardfault(rsp, elf, objdump):
    """Guest fault evidence only: BFAR, basic exception stack and opcode.

    Never suppress a fault, advance PC, write stack/registers or clear CFSR.
    The G11 nonsecure M33 EXC_RETURN=0xFFFFFFB8 has ES bit0=0;
    G1's historic decoder only accepted bit0=1, so decode locally.
    """
    fault_lr = rsp.reg(14)
    sp = rsp.reg(13)
    bfar = rsp.mem32(SCB_BFAR)
    cfsr = rsp.mem32(0xe000ed28)
    print(f"G12_FAULT_CONTEXT EXC_RETURN=0x{fault_lr:08x} "
          f"MSP=0x{sp:08x} CFSR=0x{cfsr:08x} BFAR=0x{bfar:08x}",
          flush=True)
    details = {"exc_return": fault_lr, "msp": sp, "cfsr": cfsr, "bfar": bfar}
    basic_msp_frame = (
        (fault_lr & 0xffffff00) == 0xffffff00 and
        (fault_lr & 4) == 0 and (fault_lr & 0x10) != 0 and
        (fault_lr & 2) == 0 and
        0x20000000 <= sp <= 0x2001ffe0)
    if not basic_msp_frame:
        print("G12_FAULT_FRAME_NOT_DECODED "
              "EXC_RETURN not supported basic MSP frame")
        return details
    names = ("R0", "R1", "R2", "R3", "R12", "LR", "PC", "XPSR")
    words = [rsp.mem32(sp + i * 4) for i in range(8)]
    details["stacked"] = dict(zip(names, words))
    print("G12_FAULT_FRAME " +
          " ".join(f"{n}=0x{v:08x}" for n, v in zip(names, words)),
          flush=True)
    stacked_pc = words[6]
    if not (0x6000 <= stacked_pc < 0x80000):
        print("G12_FAULT_SYMBOL_UNAVAILABLE stacked PC outside app flash")
        return details
    try:
        decoded = subprocess.run(
            [objdump, "-d", f"--start-address={max(0, stacked_pc - 4)}",
             f"--stop-address={stacked_pc + 6}", str(elf)],
            check=True, capture_output=True, text=True, timeout=15)
        useful = [line.strip() for line in decoded.stdout.splitlines()
                  if re.match(r"^[0-9a-fA-F]+:", line.strip())]
        for line in useful[-8:]:
            print(f"G12_FAULT_DISASM {line}", flush=True)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("G12_FAULT_DISASM_UNAVAILABLE")
    return details

def instruction_budget(shift, tick_hz=16000):
    """Only ns/instruction diagnostic estimate; NOT a real CPI/IPC claim."""
    if shift < 0 or shift > 20 or tick_hz <= 0:
        raise ValueError("Invalid simulated timebase")
    return (1_000_000_000 // tick_hz) / (1 << shift)


def native_wfi_locations(elf, objdump):
    """Require actual disassembled WFI opcodes inside Rel17 native main.

    Line-aligned objdump disassembly avoids incorrectly interpreting 0xBF30
    embedded in literal/data pools as a WFI instruction.
    """
    start, size = elf_function_address(elf, "am13e_rel17_app_main")
    result = subprocess.run(
        [objdump, "-d", "--disassemble=am13e_rel17_app_main", str(elf)],
        check=True, capture_output=True, text=True, timeout=20)
    matches = []
    for line in result.stdout.splitlines():
        m = re.match(r"^\s*([0-9a-fA-F]+):\s+bf30\s+wfi\b", line, re.I)
        if m:
            addr = int(m.group(1), 16)
            if start <= addr < start + size:
                matches.append(addr)
    addresses = tuple(sorted(set(matches)))
    if not addresses:
        raise AssertionError("No native Rel17 WFI found in original ELF disassembly")
    print(f"G12_NATIVE_MAIN_WFI start=0x{start:08x} size={size} "
          f"addresses={[hex(a) for a in addresses]}")
    return addresses


def int_events(path):
    """Summarize *actual* QEMU -d int messages, not heuristic PC sampling."""
    counts = collections.Counter()
    examples = []
    with path.open(encoding="utf-8", errors="replace") as src:
        for raw in src:
            line = raw.strip()
            if "taking pending" in line and "exception 15" in line:
                counts["systick_entry"] += 1
            if "taking pending" in line and "exception 14" in line:
                counts["pendsv_entry"] += 1
            if "Exception return: magic PC" in line:
                counts["excret_attempt"] += 1
            if "successful exception return" in line:
                counts["excret_success"] += 1
            if "failed exception return integrity check" in line:
                counts["excret_integrity_failure"] += 1
            if "taking UsageFault" in line:
                counts["usagefault"] += 1
            if ("taking pending" in line or
                    "failed exception return" in line):
                if len(examples) < 20:
                    examples.append(line)
    return counts, examples


def collect(shift, args, native_wfi, artifact_dir):
    with tempfile.TemporaryDirectory(prefix=f"e62-g12-s{shift}-") as td:
        wd = Path(td)
        socket_file = wd / "gdb.sock"
        cpu_log = wd / "cpu-int.log"
        cmd = [str(args.qemu.resolve()),
               "-M", "am13e23019,esc-sim=on",
               "-kernel", str(args.elf.resolve()),
               "-display", "none", "-monitor", "none", "-serial", "none",
               "-S", "-chardev",
               f"socket,path={socket_file},server=on,wait=off,id=gdb0",
               "-gdb", "chardev:gdb0",
               "-icount", f"shift={shift},sleep=off,align=off",
               "-d", "int", "-D", str(cpu_log)]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        summary = {}
        try:
            with wait_for_socket(str(socket_file), proc) as conn:
                rsp = RSP(conn)
                if not rsp.command("?").startswith(("S", "T")):
                    raise RuntimeError("QEMU did not halt at reset")
                if "qXfer:features:read+" not in rsp.command(
                        "qSupported:qXfer:features:read+"):
                    raise RuntimeError("Missing target register description")
                if not rsp.command(
                        "qXfer:features:read:target.xml:0,1").startswith(("m<", "l<")):
                    raise RuntimeError("GDB target XML unavailable")
                if rsp.command("Qqemu.sstep:1") != "OK":
                    raise RuntimeError("Cannot enable timed IRQ GDB stepping")

                release, hardfault, steps = reach_release(
                    rsp, args.elf, args.startup_steps)
                pre = observer(rsp)
                if pre["ipsr"] != 0 or pre["primask"] != 1:
                    raise AssertionError("Native CPSIE boundary not masked Thread")
                systick = elf_function_address(args.elf, "SysTick_Handler")[0]
                pendsv = elf_function_address(args.elf, "PendSV_Handler")[0]
                probes = {hardfault: "HARDFAULT",
                          systick: "SYSTICK_ENTRY",
                          pendsv: "PENDSV_ENTRY",
                          release + 2: "THREAD_AFTER_CPSIE"}
                probes.update({pc: f"MAIN_WFI_{i}" for i, pc in enumerate(native_wfi)})
                if len(probes) != 4 + len(native_wfi):
                    raise AssertionError("G12 breakpoint address collision")
                sysload = rsp.mem32(SYST_RVR)
                sysctrl = rsp.mem32(SYST_CSR)
                if not sysload or (sysctrl & 3) != 3:
                    raise AssertionError("SysTick has not been enabled by firmware")
                print(f"G12_SHIFT_{shift}_BOUNDARY "
                      f"CPSIE=0x{release:08x} MSP=0x{pre['msp']:08x} "
                      f"PRIMASK={pre['primask']} IPSR={pre['ipsr']} "
                      f"STK_LOAD={sysload} STK_CTRL=0x{sysctrl:08x} "
                      f"ns_per_instruction={1 << shift} "
                      f"estimated_instructions_per_16k_tick="
                      f"{instruction_budget(shift):.2f}",
                      flush=True)

                armed = set(probes)
                for pc in sorted(armed):
                    add_bp(rsp, pc)
                events = []
                stopped_by_timeout = False
                final = pre
                seen = set()
                try:
                    for stop_no in range(args.max_stops):
                        stop, interrupted = continue_bounded(
                            rsp, args.slice_ms)
                        if not interrupted and not stop.startswith(("S05", "T05")):
                            raise RuntimeError(f"Unexpected RSP stop {stop}")
                        state = observer(rsp)
                        final = state
                        pc = state["pc"]
                        event = ("BOUNDED_PAUSE" if interrupted else
                                 probes.get(pc, "UNEXPECTED_STOP"))
                        if not interrupted and event == "UNEXPECTED_STOP":
                            raise AssertionError(
                                f"Unrecognized GDB breakpoint stop pc=0x{pc:08x}")
                        seen.add(event)
                        data = {"event": event, "pc": pc,
                                "ipsr": state["ipsr"],
                                "primask": state["primask"],
                                "scr": rsp.mem32(SCB_SCR),
                                "icsr": state["icsr"],
                                "cfsr": state["cfsr"],
                                "hfsr": state["hfsr"]}
                        events.append(data)
                        print(f"G12_SHIFT_{shift}_STOP_{stop_no} "
                              f"EVENT={event} PC=0x{pc:08x} "
                              f"IPSR={state['ipsr']} "
                              f"PRIMASK={state['primask']} "
                              f"SCR=0x{data['scr']:08x} "
                              f"ICSR=0x{state['icsr']:08x} "
                              f"CFSR=0x{state['cfsr']:08x} "
                              f"HFSR=0x{state['hfsr']:08x}", flush=True)
                        if interrupted:
                            stopped_by_timeout = True
                            break
                        if pc == hardfault:
                            data["fault_detail"] = inspect_hardfault(
                                rsp, args.elf, args.objdump)
                            break
                        if state["cfsr"] & CFSR_INVPC:
                            break
                        # Breakpoints are one-shot, to avoid re-trapping
                        # at an identical PC while masking guest progress.
                        del_bp(rsp, pc)
                        armed.remove(pc)
                        # Do not stop at the first Thread return: G12
                        # must also probe actual Rel17 WFI locations.
                        # Thread release and motor-loop WFI are distinct
                        # milestones; only stop early once *both* IRQ
                        # handlers and a native main WFI were observed.
                        if ("SYSTICK_ENTRY" in seen and
                                "PENDSV_ENTRY" in seen and
                                any(x.startswith("MAIN_WFI") for x in seen)):
                            break
                finally:
                    for pc in sorted(armed, reverse=True):
                        del_bp(rsp, pc)

                summary = {
                    "shift": shift,
                    "ns_per_instruction": 1 << shift,
                    "inst_per_systick_period_est": instruction_budget(shift),
                    "systick_load": sysload,
                    "systick_control": sysctrl,
                    "release": release,
                    "pre": pre,
                    "final": final,
                    "events": events,
                    "reached_thread_pc": "THREAD_AFTER_CPSIE" in seen,
                    "reached_wfi": any(e.startswith("MAIN_WFI") for e in seen),
                    "reached_pendsv": "PENDSV_ENTRY" in seen,
                    "reached_systick": "SYSTICK_ENTRY" in seen,
                    "hardfault": "HARDFAULT" in seen or final["ipsr"] == 3,
                    "invpc": bool(final["cfsr"] & CFSR_INVPC),
                    "bounded_pause": stopped_by_timeout
                }
        finally:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            if cpu_log.exists():
                counters, samples = int_events(cpu_log)
                summary["qemu_cpu_int_counts"] = dict(counters)
                print(f"G12_SHIFT_{shift}_CPU_INT "
                      f"{dict(counters)}", flush=True)
                for line in samples[:6]:
                    print(f"G12_SHIFT_{shift}_CPU_INT_SAMPLE {line[:180]}")
                if artifact_dir:
                    (artifact_dir / f"g12-s{shift}-cpu-int.log").write_bytes(
                        cpu_log.read_bytes())
            if proc.stderr:
                stderr_text = proc.stderr.read()
                if stderr_text:
                    if artifact_dir:
                        (artifact_dir / f"g12-s{shift}-qemu-stderr.log").write_text(
                            stderr_text)
                    for line in stderr_text.splitlines()[-30:]:
                        print(f"G12_SHIFT_{shift}_QEMU_STDERR {line[:240]}",
                              flush=True)
                proc.stderr.close()
    print(f"G12_SHIFT_{shift}_SUMMARY "
          f"SYSTICK={int(summary['reached_systick'])} "
          f"PENDSV_BREAK={int(summary['reached_pendsv'])} "
          f"THREAD_AFTER_CPSIE={int(summary['reached_thread_pc'])} "
          f"MAIN_WFI={int(summary['reached_wfi'])} "
          f"HARDFAULT={int(summary['hardfault'])} "
          f"INVPC={int(summary['invpc'])} "
          f"BOUNDED_PAUSE={int(summary['bounded_pause'])}",
          flush=True)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", type=Path, required=True)
    ap.add_argument("--elf", type=Path, required=True)
    ap.add_argument("--objdump", default="arm-none-eabi-objdump")
    ap.add_argument("--shifts", type=int, nargs="+", default=[2, 10])
    ap.add_argument("--startup-steps", type=int, default=32768)
    ap.add_argument("--slice-ms", type=int, default=80)
    ap.add_argument("--max-stops", type=int, default=6)
    ap.add_argument("--artifact-dir", type=Path)
    ap.add_argument("--require-no-invpc", action="store_true")
    ap.add_argument("--require-shift2-progress", action="store_true",
                    help="CI gate: shift 2 must actually enter SysTick, "
                         "PendSV and resume native Thread without Fault")
    ap.add_argument("--require-thread", action="store_true",
                    help="Opt-in: at least one shift must hit native Thread PC")
    ap.add_argument("--require-pendsv", action="store_true",
                    help="Opt-in: at least one shift must hit native PendSV")
    ap.add_argument("--require-wfi", action="store_true",
                    help="Opt-in: at least one shift must hit a native main WFI")
    args = ap.parse_args()
    if not args.qemu.is_file() or not args.elf.is_file():
        ap.error("Both QEMU binary and original ELF must exist")
    if not (1 <= args.startup_steps <= 65536 and
            10 <= args.slice_ms <= 1000 and
            1 <= args.max_stops <= 20 and
            1 <= len(args.shifts) <= 4 and
            len(set(args.shifts)) == len(args.shifts) and
            all(0 <= shift <= 12 for shift in args.shifts)):
        ap.error("Unsupported G12 timebase or execution bound")
    app_vector_from_elf(args.elf)
    wfi = native_wfi_locations(args.elf, args.objdump)
    if args.artifact_dir:
        args.artifact_dir.mkdir(parents=True, exist_ok=True)
    results = [collect(shift, args, wfi, args.artifact_dir)
               for shift in args.shifts]
    if args.artifact_dir:
        (args.artifact_dir / "g12-runtime-progress.json").write_text(
            json.dumps(results, indent=2) + "\n")
    if args.require_no_invpc and any(x["invpc"] for x in results):
        raise AssertionError("G12 native INVPC regression")
    if args.require_shift2_progress:
        case = next((x for x in results if x["shift"] == 2), None)
        if case is None or not (
                case["reached_systick"] and case["reached_pendsv"] and
                case["reached_thread_pc"] and not case["hardfault"] and
                not case["invpc"]):
            raise AssertionError("G12 shift=2 has not demonstrated "
                                 "SysTick -> PendSV -> native Thread")
        print("PASS_G12_NATIVE_SYSTICK_PENDSV_THREAD_SHIFT2")
    for name, enabled, predicate in [
        ("THREAD", args.require_thread, lambda x: x["reached_thread_pc"]),
        ("PENDSV", args.require_pendsv, lambda x: x["reached_pendsv"]),
        ("WFI", args.require_wfi, lambda x: x["reached_wfi"])
    ]:
        if enabled and not any(predicate(x) for x in results):
            raise AssertionError(
                f"G12 {name}: no native evidence in tested timebases")
    print("G12_COMPARISON " + " ".join(
        f"shift={x['shift']}:thread={int(x['reached_thread_pc'])},"
        f"pendsv={int(x['reached_pendsv'])},"
        f"wfi={int(x['reached_wfi'])},"
        f"invpc={int(x['invpc'])}"
        for x in results))
    print("PASS_G12_BOUNDED_NATIVE_RUNTIME_DIAGNOSTIC_ONLY "
          "NO_AUTOMATIC_BOOT_OR_REALTIME_QUALIFICATION")


if __name__ == "__main__":
    main()
