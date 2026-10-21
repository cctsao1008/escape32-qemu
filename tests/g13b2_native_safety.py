#!/usr/bin/env python3
"""G13B2C native SIM_ONLY *neutral* protection-ready readback.

The original ELF is compiled with explicit TEST-ONLY electrical profile.
QTest writes only analog current *external samples* (no guest regs, fault
flags, MMIO config or manual gate). Native firmware owns initialization of
all CMPSS1/2/3, INPUTXBAR/PWMXBAR, PA22 and MCPWM4 TZ. CPU must reach an
actual native WFI (neutral command, not arming), with power stage OFF and
all 3 independent protection routes genuine/ready. Not closed-loop.
"""
import argparse
import json
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from g0_memory import QTest
from g1_handoff import RSP, wait_for_socket
from g11_exception_lifecycle import reach_release, observer, add_bp, del_bp
from g12_runtime_progress import native_wfi_locations
from g13b_native_wfi import wait_for_native_main_wfi
from g13b_native_no_drive import symbol_address
from elf_image import app_vector_from_elf
from tools.virtual_bldc import PINCM_BASE, GPIO1_BASE, GATE_EN, MCPWM4_ROUTES

EXT_OC = 0x5ffe5000
GPIO0 = 0x400f0000
PWM4 = 0x40014000
PWMXBAR = 0x40469000
INPUTXBAR = 0x40468000
CMP = (0x40461000, 0x40462000, 0x40463000)
PWM_OBS = 0x5ffe1000
SCB_CFSR = 0xe000ed28
SCB_HFSR = 0xe000ed2c


def snapshot(rsp, throt_addr):
    read = rsp.mem32
    data = {
        "cpu": observer(rsp),
        "throt": read(throt_addr),
        "oc_compctl": [rsp.mem16(base) for base in CMP],
        "oc_dach_active": [rsp.mem16(base + 0xe) for base in CMP],
        "oc_external": [read(EXT_OC + i*4) for i in range(3)],
        "nfault": read(GPIO0 + 0x1380) & (1 << 22),
        "pa22_pincm": read(PINCM_BASE + 4*22),
        "inputxbar2_select": read(INPUTXBAR + 4),
        "raw_gpio22": read(INPUTXBAR + 0x410) & (1 << 22),
        "trip2_g0": read(PWMXBAR + 0x140),
        "trip3_g0": read(PWMXBAR + 0x180),
        "trip_invert": read(PWMXBAR + 0x30),
        "tzsel": read(PWM4 + 0xa0),
        "tzctl": read(PWM4 + 0xac),
        "tzflags": read(PWM4 + 0xb0),
        "pwm_running": read(PWM_OBS) & 1,
        "perclkcr": read(0x400b048c),
        "pb13_doe": read(GPIO1_BASE + 0x12c0) & GATE_EN,
        "pb13_dout": read(GPIO1_BASE + 0x1280) & GATE_EN,
        "pb13_pincm": read(PINCM_BASE + 4*45),
        "pwm_pad_pincm": [read(PINCM_BASE + 4*pin) for pin, _ in MCPWM4_ROUTES],
        "cfsr": read(SCB_CFSR), "hfsr": read(SCB_HFSR)
    }
    return data


def verify(state):
    c = state["cpu"]
    if c["ipsr"] != 0 or c["primask"] != 0:
        raise AssertionError("Native firmware has not reached healthy Thread")
    if state["cfsr"] or state["hfsr"]:
        raise AssertionError("SIM_ONLY native startup has CPU fault")
    if state["throt"] not in (0, 1):
        raise AssertionError("No-command SIM_ONLY unexpectedly armed throttle")
    if state["pb13_dout"] or state["pwm_running"] or state["perclkcr"] & 1:
        raise AssertionError("Native SIM_ONLY neutral WFI activated physical gate/PWM")
    # Configured SIM_ONLY native board makes PB13 a digital GPIO
    # OUTPUT with its DATA driven to the explicitly declared inactive
    # level. TI PINCM GPIO output is 0x00000081 (INENA=0);
    # 0x00040081 would be GPIO input (INENA=1), which is the
    # unqualified Reference fail-closed default, not this board.
    if (state["pb13_doe"] != GATE_EN or
            state["pb13_dout"] != 0 or
            (state["pb13_pincm"] & 0x000400bf) != 0x00000081):
        raise AssertionError(
            "SIM_ONLY PB13 must be OUTPUT with inactive data and "
            "output-function PINCM; no Gate authorization inferred")
    if state["pa22_pincm"] & 0x000400bf != 0x00040081:
        raise AssertionError("PA22 nFAULT pin was not made a GPIO input")
    if (state["inputxbar2_select"] != 22 or
            not state["raw_gpio22"] or
            state["trip2_g0"] != 0x200000 or
            state["trip3_g0"] != 0x54 or
            state["trip_invert"] & 6 != 2):
        raise AssertionError("Real native input/phase-OC trip XBAR not configured")
    if (state["tzsel"] & 0x60000) != 0x60000 or (
            state["tzctl"] & 0xf) != 0xa or state["tzflags"] & 0x60000:
        raise AssertionError("Native MCPWM4 TZ actions or status invalid")
    if any(x != 2048 for x in state["oc_dach_active"]):
        raise AssertionError("All three native DACH thresholds missing")
    if any((x & 0x8001) != 0x8000 for x in state["oc_compctl"]):
        raise AssertionError("CMPSS1-3 high DAC/CTRIPH not native enabled")
    if any(x != (0x10000 | 1000) for x in state["oc_external"]):
        raise AssertionError("Explicit analog fixture was lost")
    if any((x & 0x000400bf) != 0x00040081 for x in state["pwm_pad_pincm"]):
        raise AssertionError("Native PWM pads connected with neutral input")
    print("PASS_G13B2C_NATIVE_CMPSS123_INPUTXBAR_PWMXBAR_OST23_CONFIGURED "
          "NEUTRAL_GATE_OFF_NOT_CLOSED_LOOP", flush=True)


def run(args):
    app_vector_from_elf(args.elf)
    wfi = native_wfi_locations(args.elf, args.objdump)
    throt_addr = symbol_address(args.elf, "throt")
    with tempfile.TemporaryDirectory(prefix="g13b2-native-") as tmp:
        qtpath = str(Path(tmp) / "qtest.sock")
        gdbpath = str(Path(tmp) / "gdb.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(qtpath)
            listener.listen(1)
            listener.settimeout(15)
            cmd = [
                str(args.qemu.resolve()), "-M",
                "am13e23019,esc-sim=on,esc-sim-nfault-asserted=off",
                "-kernel", str(args.elf.resolve()),
                "-S", "-display", "none", "-serial", "none", "-monitor", "none",
                "-chardev", f"socket,path={gdbpath},server=on,wait=off,id=gdb0",
                "-gdb", "chardev:gdb0",
                "-qtest", f"unix:path={qtpath}",
                "-icount", "shift=2,sleep=off,align=off"
            ]
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, text=True)
            qtconn = None
            try:
                qtconn, _ = listener.accept()
                q = QTest(qtconn)
                for phase in range(3):
                    q.write(EXT_OC + 4*phase, 0x10000 | 1000)
                assert all(q.read(EXT_OC + 4*i) == (0x10000 | 1000)
                           for i in range(3))
                print("G13B2C_EXTERNAL_HEALTHY_CURRENT_FIXTURE_THREE_PHASES "
                      "TEST_ONLY_NOT_GUEST_SRAM", flush=True)
                with wait_for_socket(gdbpath, proc) as conn:
                    rsp = RSP(conn)
                    if not rsp.command("?").startswith(("S", "T")):
                        raise RuntimeError("Native CPU did not halt")
                    if "qXfer:features:read+" not in rsp.command(
                            "qSupported:qXfer:features:read+"):
                        raise RuntimeError("Missing GDB target XML")
                    if not rsp.command(
                            "qXfer:features:read:target.xml:0,1").startswith(
                                ("m<", "l<")):
                        raise RuntimeError("Cannot obtain target XML")
                    if rsp.command("Qqemu.sstep:1") != "OK":
                        raise RuntimeError("Timed GDB stepping unavailable")
                    release, hardfault, count = reach_release(
                        rsp, args.elf, args.startup_steps)
                    armed = {*wfi, hardfault}
                    for pc in sorted(armed):
                        add_bp(rsp, pc)
                    try:
                        pc = wait_for_native_main_wfi(
                            rsp, wfi, hardfault,
                            args.slice_ms, args.runtime_slices,
                            stage="B2C_NATIVE_NEUTRAL_WFI")
                        sample = snapshot(rsp, throt_addr)
                        print("G13B2C_NATIVE_NEUTRAL_SNAPSHOT " +
                              json.dumps(sample, sort_keys=True), flush=True)
                        verify(sample)
                        if args.artifact:
                            args.artifact.parent.mkdir(parents=True, exist_ok=True)
                            args.artifact.write_text(
                                json.dumps(sample, indent=2) + "\n")
                    finally:
                        for pc in sorted(armed, reverse=True):
                            del_bp(rsp, pc)
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
                        print("G13B2C_QEMU_STDERR " +
                              proc.stderr.read()[-2500:])
                    proc.stderr.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    p.add_argument("--objdump", default="arm-none-eabi-objdump")
    p.add_argument("--startup-steps", type=int, default=32768)
    p.add_argument("--slice-ms", type=int, default=150)
    p.add_argument("--runtime-slices", type=int, default=12)
    p.add_argument("--artifact", type=Path)
    args = p.parse_args()
    if not args.qemu.is_file() or not args.elf.is_file():
        p.error("Missing compiled QEMU or SIM_ONLY native ELF")
    run(args)


if __name__ == "__main__":
    main()
