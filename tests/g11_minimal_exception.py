#!/usr/bin/env python3
"""G11E isolated IRQ exception entry+return control on the same Cortex-M33.

Runs ONLY tests/fixtures/g11_pendsv_irq.elf, never patches the ESCape32 ELF.
A successful control rules out gross broken PendSV entry/return on this
simulated core but cannot rule out the original SysTick/PendSV interaction.
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

from g1_handoff import RSP, wait_for_socket
from elf_image import app_vector_from_elf

OBS = 0x5ffe3000
COUNTER = 0x20000000
MARKER = 0x20000004
CFSR = 0xe000ed28
HFSR = 0xe000ed2c

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", required=True, type=Path)
    ap.add_argument("--elf", required=True, type=Path,
                    help="Isolated g11_pendsv_irq.elf, NEVER ESCape32 ELF")
    ap.add_argument("--artifact-dir", type=Path)
    args = ap.parse_args()
    for path in (args.qemu, args.elf):
        if not path.is_file():
            ap.error("Missing file: " + str(path))
    app_vector_from_elf(args.elf)
    if args.artifact_dir:
        args.artifact_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="am13e-g11-control-") as td:
        p = Path(td)
        sock = p / "gdb.sock"
        cpulog = p / "g11-control-cpu-int.log"
        cmd = [str(args.qemu.resolve()), "-M", "am13e23019,esc-sim=on",
               "-kernel", str(args.elf.resolve()), "-S",
               "-display", "none", "-monitor", "none", "-serial", "none",
               "-chardev",
               f"socket,path={sock},server=on,wait=off,id=gdb0",
               "-gdb", "chardev:gdb0",
               "-icount", "shift=10,sleep=off,align=off",
               "-d", "int", "-D", str(cpulog)]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            with wait_for_socket(str(sock), proc) as conn:
                rsp = RSP(conn)
                if not rsp.command("?").startswith(("T", "S")):
                    raise RuntimeError("QEMU failed to halt at reset")
                if "qXfer:features:read+" not in rsp.command(
                        "qSupported:qXfer:features:read+"):
                    raise RuntimeError("Missing GDB target XML")
                rsp.command("qXfer:features:read:target.xml:0,1")
                if rsp.command("Qqemu.sstep:1") != "OK":
                    raise RuntimeError("Cannot enable IRQ/timer single stepping")
                if rsp.mem32(OBS + 4) != 1:
                    raise AssertionError("G11 fixture did not inherit masked handoff")
                transitions = []
                last_ipsr = rsp.reg(25) & 0x1ff
                step = 0
                for step in range(1, 192):
                    result = rsp.command("s")
                    if not result.startswith(("S05", "T05")):
                        raise RuntimeError(f"Unexpected GDB stop {result}")
                    ipsr = rsp.reg(25) & 0x1ff
                    if ipsr != last_ipsr:
                        transitions.append((step, ipsr, rsp.reg(15)))
                        last_ipsr = ipsr
                    flag = rsp.mem32(MARKER)
                    if flag in (0x5a, 0xee, 0xff):
                        break
                flag = rsp.mem32(MARKER)
                count = rsp.mem32(COUNTER)
                cfsr = rsp.mem32(CFSR)
                hfsr = rsp.mem32(HFSR)
                mask = rsp.mem32(OBS + 4)
                mode = rsp.mem32(OBS + 0x1c)
                print(f"G11_CONTROL_RESULT steps={step} "
                      f"MARKER=0x{flag:02x} PENDSV_COUNT={count} "
                      f"PRIMASK={mask} IPSR={mode} "
                      f"CFSR=0x{cfsr:08x} HFSR=0x{hfsr:08x} "
                      f"TRANSITIONS={transitions}")
                if flag != 0x5a or count != 1 or mask != 0 or cfsr != 0:
                    raise AssertionError("Independent PendSV entry/return failed")
                if not any(e[1] == 14 for e in transitions):
                    raise AssertionError("PendSV handler was never observed")
                if not any(e[1] == 0 for e in transitions[1:]):
                    raise AssertionError("PendSV did not return to Thread")
                print("PASS_G11E_INDEPENDENT_PENDSV_EXCEPTION_ENTRY_AND_RETURN")
        finally:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            if cpulog.exists() and args.artifact_dir:
                (args.artifact_dir / "g11-control-cpu-int.log").write_text(
                    cpulog.read_text(errors="replace"))
            proc.stderr.close()

if __name__ == "__main__":
    main()
