#!/usr/bin/env python3
"""G1 test: read real Cortex-M33 CPU state via QEMU GDB RSP and step ELF.

No application binary rewriting, replacement startup, fake MMIO, or motor.
"""
import argparse
import os
import re
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from collections import Counter, deque
from elf_image import APP_BASE, app_vector_from_elf, elf_function_address


class RSP:
    def __init__(self, sock):
        self.sock = sock
        self.sock.settimeout(8)

    def byte(self):
        data = self.sock.recv(1)
        if not data:
            raise RuntimeError("GDB stub closed the connection")
        return data

    def command(self, payload):
        raw = payload.encode("ascii")
        checksum = sum(raw) & 255
        self.sock.sendall(b"$" + raw + f"#{checksum:02x}".encode())
        ack = self.byte()
        if ack != b"+":
            raise RuntimeError(f"Unexpected GDB RSP ACK: {ack!r}")
        start = self.byte()
        if start != b"$":
            raise RuntimeError(f"Unexpected GDB RSP reply start: {start!r}")
        packet = bytearray()
        while True:
            char = self.byte()
            if char == b"#":
                break
            packet.extend(char)
        sent = self.byte() + self.byte()
        if sent.decode("ascii").lower() != f"{sum(packet) & 255:02x}":
            self.sock.sendall(b"-")
            raise RuntimeError("Invalid RSP reply checksum")
        self.sock.sendall(b"+")
        result = packet.decode("ascii")
        # RSP errors are exactly 'E' followed by two hex digits.
        # 'ENABLE=1,NOIRQ=2,NOTIMER=4' is a valid QEMU feature reply.
        if re.fullmatch(r"E[0-9a-fA-F]{2}", result):
            raise RuntimeError(f"GDB RSP error for {payload}: {result}")
        return result

    def reg(self, n):
        result = self.command(f"p{n:x}")
        if len(result) != 8 or "x" in result:
            raise RuntimeError(f"Unavailable RSP register {n}: {result}")
        return struct.unpack("<I", bytes.fromhex(result))[0]

    def mem32(self, address):
        raw = self.command(f"m{address:x},4")
        if len(raw) != 8:
            raise RuntimeError(f"Cannot read CPU memory 0x{address:08x}: {raw}")
        return struct.unpack("<I", bytes.fromhex(raw))[0]

    def mem16(self, address):
        raw = self.command(f"m{address:x},2")
        if len(raw) != 4:
            raise RuntimeError(f"Cannot read Thumb opcode 0x{address:08x}: {raw}")
        return struct.unpack("<H", bytes.fromhex(raw))[0]


def wait_for_socket(path, process, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError(f"QEMU exited early: {process.stderr.read()}")
        try:
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.connect(path)
            return conn
        except (FileNotFoundError, ConnectionRefusedError):
            conn.close()
            time.sleep(0.05)
    raise TimeoutError(f"QEMU GDB socket did not appear: {path}")



# Source: TI SDK dl_common.c.  Resolve this function from the real ELF:
# the native HAL fix changed linked addresses, but not SDK delay logic.
# The diagnostic checks loop opcodes, then QEMU executes real instructions.


def fast_forward_sdk_delay(rsp, pc, hardfault_pc, sdk_delay_loop):
    """Execute a verified delay via GDB continue-to-LR, without skipping CPU."""
    if pc not in sdk_delay_loop:
        return None
    nop = rsp.mem16(sdk_delay_loop[1])
    branch = rsp.mem16(sdk_delay_loop[2])
    if (nop, branch) != (0xBF00, 0xD2FC):
        raise RuntimeError(
            f"SDK delay loop opcode mismatch: NOP=0x{nop:04x} "
            f"BHS=0x{branch:04x}; fast-forward rejected")
    ret = rsp.reg(14) & ~1
    if not (APP_BASE <= ret < 0x80000) or ret in sdk_delay_loop:
        raise RuntimeError(f"Unexpected SDK delay LR=0x{ret:08x}")
    breakpoints = tuple(dict.fromkeys((ret, hardfault_pc)))
    installed = []
    try:
        for address in breakpoints:
            reply = rsp.command(f"Z0,{address:x},2")
            if reply != "OK":
                raise RuntimeError(f"Cannot install GDB breakpoint at "
                                   f"0x{address:08x}: {reply}")
            installed.append(address)
        try:
            stop = rsp.command("c")
        except socket.timeout as exc:
            raise TimeoutError("SDK delay did not return within GDB timeout; "
                               "no success inferred") from exc
    finally:
        for address in reversed(installed):
            reply = rsp.command(f"z0,{address:x},2")
            if reply != "OK":
                raise RuntimeError(f"Failed to remove GDB breakpoint at "
                                   f"0x{address:08x}: {reply}")
    if not stop.startswith(("S05", "T05")):
        raise RuntimeError(f"Unexpected GDB stop during SDK delay: {stop}")
    observed = rsp.reg(15)
    if observed not in breakpoints:
        raise RuntimeError(f"SDK delay stopped at unknown 0x{observed:08x}, "
                           f"not return=0x{ret:08x} or fault")
    print(f"G1_DELAY_CONTINUE loop=0x{sdk_delay_loop[0]:08x} "
          f"return=0x{ret:08x} stop=0x{observed:08x} "
          "GUEST_INSTRUCTIONS_EXECUTED")
    return observed


def print_fault_snapshot(rsp):
    """Observe exception state only; never clear status bits or alter CPU."""
    sp, lr, pc, xpsr = (rsp.reg(n) for n in (13, 14, 15, 25))
    ipsr = xpsr & 0x1ff
    print(f"G1_FAULT_CPU SP=0x{sp:08x} LR=0x{lr:08x} "
          f"PC=0x{pc:08x} XPSR=0x{xpsr:08x} IPSR={ipsr}")
    regs = (
        ("ICSR", 0xE000ED04),
        ("SHCSR", 0xE000ED24),
        ("CFSR", 0xE000ED28),
        ("HFSR", 0xE000ED2C),
        ("DFSR", 0xE000ED30),
        ("MMFAR", 0xE000ED34),
        ("BFAR", 0xE000ED38),
    )
    values = {}
    for name, address in regs:
        try:
            values[name] = f"0x{rsp.mem32(address):08x}"
        except (RuntimeError, OSError, ValueError) as exc:
            values[name] = f"unavailable({type(exc).__name__})"
    print("G1_FAULT_SCB " + " ".join(f"{key}={value}"
                                   for key, value in values.items()))
    if ipsr != 3:
        print("G1_FAULT_NOTE Handler vector reached, but IPSR is not 3; "
              "do not infer HardFault exception.")
        return
    # We are stopped at vector entry before the Handler prologue.
    # Inspect a basic hardware frame only when EXC_RETURN indicates MSP
    # and a basic (non-extended-FP) exception frame.
    # Armv8-M EXC_RETURN can carry security-state bits in [7:5].
    # The old FFFFFFE0 mask incorrectly rejected observed 0xFFFFFFB9.
    # We only decode the basic MSP frame for architecturally plausible
    # EXC_RETURN encodings; no exception state is changed.
    is_exc_return = ((lr & 0xffffff00) == 0xffffff00 and
                     (lr & 0x1f) in (0x11, 0x19, 0x1d))
    using_msp = not (lr & (1 << 2))
    basic_frame = bool(lr & (1 << 4))
    if (is_exc_return and using_msp and basic_frame and
            0x20000000 <= sp <= 0x2001ffe0):
        try:
            names = ("R0", "R1", "R2", "R3", "R12", "LR", "PC", "XPSR")
            words = [rsp.mem32(sp + 4 * i) for i in range(8)]
            print("G1_FAULT_STACK " + " ".join(
                f"{name}=0x{value:08x}" for name, value in zip(names, words)))
            print(f"G1_FAULT_SITE stacked_PC=0x{words[6]:08x} "
                  f"stacked_LR=0x{words[5]:08x}")
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"G1_FAULT_STACK unavailable: {exc}")
    else:
        print("G1_FAULT_STACK unavailable: exception return does not "
              "identify an MSP basic frame")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--xtal-present", action="store_true",
                        help="Opt in to G2g virtual 25MHz XTAL fixture")
    parser.add_argument("--esc-sim", action="store_true",
                        help="Opt in to synthetic functional ESC startup defaults")
    parser.add_argument("--factory-pll-file", type=Path,
                        help="Explicit 8-byte little-endian Factory PLL pair (no default)")
    parser.add_argument("--timed-steps", action="store_true",
                        help="Use QEMU 6.2 icount shift=10 and enable GDB timer steps (diagnostic)")
    parser.add_argument("--fast-delay-loops", action="store_true",
                        help="GDB continue-to-return for verified SDK cycle delay")
    parser.add_argument("--require-pwm4-init", action="store_true",
                        help="Fail unless the guest enabled PWM4 power and initialized native TBCTL/TBPRD")
    parser.add_argument("--require-ecap1-init", action="store_true",
                        help="Fail unless native ECAP1 capture registers are initialized after PWM4")
    parser.add_argument("--startup-steps", type=int, default=1,
                        help="Bounded CPU single-step trace; 1 is the original G1 check")
    args = parser.parse_args()
    if not 1 <= args.startup_steps <= 32768:
        parser.error("--startup-steps must be between 1 and 32768")
    if args.timed_steps and not (args.xtal_present or args.esc_sim):
        parser.error("--timed-steps requires --xtal-present or --esc-sim")
    if args.fast_delay_loops and not (args.esc_sim and args.timed_steps):
        parser.error("--fast-delay-loops requires --esc-sim --timed-steps")
    if args.require_pwm4_init and (not args.esc_sim or args.startup_steps == 1):
        parser.error("--require-pwm4-init requires --esc-sim and an extended trace")
    if args.require_ecap1_init and (not args.esc_sim or
                                     not args.require_pwm4_init or
                                     args.startup_steps == 1):
        parser.error("--require-ecap1-init requires --esc-sim, --require-pwm4-init and extended trace")
    qemu, elf = args.qemu.resolve(), args.elf.resolve()
    for file in (qemu, elf):
        if not file.is_file():
            parser.error(f"Missing file: {file}")
    if args.factory_pll_file is not None and not args.factory_pll_file.is_file():
        parser.error(f"Missing factory fixture: {args.factory_pll_file}")
    expected_sp, expected_reset = app_vector_from_elf(elf)
    delay_addr, delay_size = elf_function_address(elf, "DL_Common_delayCycles")
    if delay_size != 10:
        raise RuntimeError("SDK delay function changed; cannot accelerate")
    sdk_delay_loop = (delay_addr + 2, delay_addr + 4, delay_addr + 6)
    with tempfile.TemporaryDirectory(prefix="am13e-g1-") as tmp:
        socket_path = os.path.join(tmp, "gdb.sock")
        cmd = [
            str(qemu), "-M",
            "am13e23019,xtal-present=" +
            ("on" if args.xtal_present else "off"),
            "-kernel", str(elf),
            "-display", "none", "-monitor", "none", "-serial", "none",
            "-S",
            "-chardev", f"socket,path={socket_path},server=on,wait=off,id=gdb0",
            "-gdb", "chardev:gdb0",
        ]
        if args.esc_sim:
            cmd[2] += ",esc-sim=on"
        if args.factory_pll_file is not None:
            # Keep the original ELF unaltered; provision only the
            # physically separate FACTORY window via an explicit fixture.
            cmd[2] += ",factory-pll-file=" + str(args.factory_pll_file.resolve())
        if args.timed_steps:
            # 1024 virtual ns/instruction (max supported QEMU 6.2 icount shift=10).
            # NOT the real AM13E 200MHz instruction/cycle rate.
            cmd += ["-icount", "shift=10,sleep=off,align=off"]
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, text=True)
        try:
            with wait_for_socket(socket_path, process) as conn:
                rsp = RSP(conn)
                halt = rsp.command("?")
                if not halt.startswith(("S", "T")):
                    raise RuntimeError(f"Unexpected CPU stop reply: {halt}")
                # QEMU 6.2 returns an empty reply to 'pN' until the
                # client requests target XML (gdbstub.c:handle_get_reg).
                # Fetch one XML byte: this enables XML-aware register reads
                # without needing a full XML parser or changing the guest.
                supported = rsp.command("qSupported:qXfer:features:read+")
                if "qXfer:features:read+" not in supported:
                    raise RuntimeError("QEMU GDB stub does not support target XML")
                xml_probe = rsp.command("qXfer:features:read:target.xml:0,1")
                if not xml_probe.startswith(("m<", "l<")):
                    raise RuntimeError(f"Unexpected target XML reply: {xml_probe!r}")
                if args.timed_steps:
                    # QEMU 6.2 GDB default SSTEP_NOTIMER=4 blocks clock
                    # event callbacks during 's'. SSTEP_ENABLE=1 allows
                    # the guest to see scheduled virtual XTAL readiness.
                    bits = rsp.command("qqemu.sstepbits")
                    if "ENABLE=1" not in bits or "NOTIMER=4" not in bits:
                        raise RuntimeError(f"Unexpected QEMU sstep bits: {bits!r}")
                    accepted = rsp.command("Qqemu.sstep:1")
                    if accepted != "OK":
                        raise RuntimeError(f"Cannot enable timer steps: {accepted!r}")
                    active = rsp.command("qqemu.sstep")
                    if active != "0x1":
                        raise RuntimeError(f"Timer single-step mode not set: {active!r}")
                    print("G1_TIMED_STEPS icount_shift=10 ns_per_insn=1024 "
                          "qemu_sstep=0x1 DIAGNOSTIC_ONLY")
                sp, pc, xpsr = rsp.reg(13), rsp.reg(15), rsp.reg(25)
                vt = rsp.mem32(0xE000ED08)
                pfr1 = rsp.mem32(0xE000ED44)
                vec_sp, vec_pc = rsp.mem32(APP_BASE), rsp.mem32(APP_BASE + 4)
                print(f"APP_VECTOR SP=0x{vec_sp:08x} RESET=0x{vec_pc:08x}")
                print(f"G1_HANDOFF SP=0x{sp:08x} PC=0x{pc:08x} "
                      f"XPSR=0x{xpsr:08x} VTOR=0x{vt:08x} PFR1=0x{pfr1:08x}")
                assert (vec_sp, vec_pc) == (expected_sp, expected_reset), "QEMU flash vector differs from supplied ELF"
                assert sp == vec_sp and pc == (vec_pc & ~1), "CPU initial MSP/PC does not match original ELF"
                assert xpsr & 0x01000000, "Thumb state was not set"
                assert vt == APP_BASE, "Application VTOR was not relocated"
                assert (pfr1 & 0xF0) == 0, "M33 Security Extension still advertised"

                stop = rsp.command("s")
                if not stop.startswith(("S", "T")):
                    raise RuntimeError(f"CPU did not stop after stepping: {stop}")
                new_pc = rsp.reg(15)
                print(f"G1_STEP initial_PC=0x{pc:08x} next_PC=0x{new_pc:08x}")
                if new_pc == pc:
                    raise AssertionError("Original reset instruction did not advance PC")
                print("PASS_G1_APP_HANDOFF_AND_FIRST_INSTRUCTION")
                print("NOTE: PRIMASK=1 is applied by board reset callback; "
                      "not independently read by this GDB test.")
                print("NOTE: SYSCTL/FRI and FACTORY models are partial; XTAL Ready requires an explicit virtual fixture. No SYSPLL lock or motor hardware modeled.")
                if args.startup_steps > 1:
                    # The first instruction was already stepped above.
                    # Trace is diagnostic: instruction count is NOT evidence
                    # that clock/peripherals or the ESC are initialized.
                    hardfault_pc = rsp.mem32(APP_BASE + 3 * 4) & ~1
                    history = deque([pc, new_pc], maxlen=16)
                    hot = Counter((pc, new_pc))
                    current = new_pc
                    completed = 1
                    fast_delays = 0
                    ecap_caplden_seen = False
                    reason = "step-limit"
                    if current == hardfault_pc:
                        reason = "hardfault-vector"
                    else:
                        for i in range(2, args.startup_steps + 1):
                            response = rsp.command("s")
                            if not response.startswith(("S", "T")):
                                raise RuntimeError(f"Unexpected step response: {response}")
                            if response[:3] not in ("S05", "T05"):
                                raise RuntimeError(f"Guest stopped unexpectedly: {response}")
                            current = rsp.reg(15)
                            if args.fast_delay_loops and current in sdk_delay_loop:
                                # Continue actually runs the busywait in QEMU;
                                # this iteration counts one host GDB stop,
                                # not its many guest instructions.
                                current = fast_forward_sdk_delay(
                                    rsp, current, hardfault_pc, sdk_delay_loop)
                                fast_delays += 1
                            hot[current] += 1
                            history.append(current)
                            completed = i
                            # The safe-stop policy may clear CAPLDEN after
                            # initialization. Sample during guest execution.
                            if args.require_ecap1_init and i % 16 == 0:
                                power_sample = rsp.mem32(0x400B0424)
                                if power_sample & (1 << 4):
                                    sample_ecctl1 = rsp.mem16(0x40441028)
                                    if sample_ecctl1 & 0x100:
                                        ecap_caplden_seen = True
                            if i <= 12 or i % 256 == 0:
                                print(f"G1_TRACE step={i} PC=0x{current:08x}")
                            if current == hardfault_pc:
                                reason = "hardfault-vector"
                                break
                    top = " ".join(f"0x{address:08x}:{count}"
                                   for address, count in hot.most_common(6))
                    recent = " ".join(f"0x{address:08x}" for address in history)
                    print(f"G1_TRACE_SUMMARY steps={completed} reason={reason} "
                          f"unique_pcs={len(hot)} current_pc=0x{current:08x} "
                          f"delay_continue_count={fast_delays}")
                    if fast_delays:
                        print("G1_TRACE_COUNT_NOTE steps=GDB_OBSERVATIONS "
                              "not all guest instructions after continue")
                    print(f"G1_TRACE_HOT_PCS {top}")
                    print(f"G1_TRACE_RECENT_PCS {recent}")
                    if reason == "hardfault-vector":
                        print_fault_snapshot(rsp)
                    if args.require_pwm4_init:
                        # This is a guest-observed HAL initialization proof,
                        # not a host-written register fixture or motor PASS.
                        power = rsp.mem32(0x400B0424)  # PWREN_MCPERIPH
                        tbctl = rsp.mem32(0x40014010)  # MCPWM4.TBCTL
                        period = rsp.mem32(0x40014014) # MCPWM4.TBPRD
                        print(f"G1_PWM4_INIT_OBSERVED PWREN=0x{power:08x} "
                              f"TBCTL=0x{tbctl:08x} TBPRD={period} "
                              f"reason={reason}")
                        if reason == "hardfault-vector":
                            cfsr = rsp.mem32(0xE000ED28)
                            bfar = rsp.mem32(0xE000ED38)
                            if cfsr & 0x8000 and bfar == 0x40014010:
                                raise AssertionError("Original MCPWM4.TBCTL BusFault persists")
                        # 200MHz MCLK, SDK prescaler /2, 24kHz
                        # inactive carrier: 4165 is original HAL config.
                        if ((power & (1 << 9)) == 0 or
                                tbctl & 0x3f != 0x06 or period != 4165):
                            raise AssertionError("MCPWM4 initialization has not completed")
                        print("PASS_G1_NATIVE_PWM4_HAL_INITIALIZATION_ONLY")
                    if args.require_ecap1_init:
                        # Read native TI ECAP1 registers observed from the
                        # guest execution, not prewritten host test values.
                        power = rsp.mem32(0x400B0424)
                        ecctl0 = rsp.mem32(0x40441024)
                        ecctl1 = rsp.mem16(0x40441028)
                        ecctl2 = rsp.mem16(0x4044102a)
                        tsctr = rsp.mem32(0x40441000)
                        ecap_caplden_seen |= bool(ecctl1 & 0x100)
                        print(f"G1_ECAP1_INIT_OBSERVED PWREN=0x{power:08x} "
                              f"ECCTL0=0x{ecctl0:08x} "
                              f"ECCTL1_FINAL=0x{ecctl1:04x} "
                              f"CAPLDEN_EVER_ENABLED={int(ecap_caplden_seen)} "
                              f"ECCTL2=0x{ecctl2:04x} TSCTR={tsctr} "
                              f"reason={reason}")
                        if reason == "hardfault-vector":
                            cfsr = rsp.mem32(0xE000ED28)
                            bfar = rsp.mem32(0xE000ED38)
                            if cfsr & 0x8000 and bfar == 0x4044102a:
                                raise AssertionError("Original ECAP1.ECCTL2 BusFault persists")
                        if ((power & (1 << 4)) == 0 or
                                (ecctl0 & 0x7f) != 45 or
                                not ecap_caplden_seen or
                                (ecctl2 & 0x10) == 0):
                            raise AssertionError("Native ECAP1 capture initialization incomplete")
                        print("PASS_G1_NATIVE_ECAP1_CAPTURE_INITIALIZATION_ONLY")
                    print("TRACE_ONLY: no startup, clock, peripheral or "
                          "safety-readiness verdict from instruction counts.")
        except Exception:
            if process.poll() is not None:
                print("QEMU stderr:", process.stderr.read())
            raise
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            process.stderr.close()


if __name__ == "__main__":
    main()
