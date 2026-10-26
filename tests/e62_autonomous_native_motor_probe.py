#!/usr/bin/env python3
"""E62 experimental no-GDB/no-WFI original-Guest native motor smoke.

Runs the Original ELF normally in QEMU. The only host writes target
the non-silicon autonomous PA26 DShot stage input port, before execution
of the scenario. Native QEMU virtual timers own PWM→current→rotor→BEMF.
No Guest SRAM, IRQ, CAP1, MCPWM or comparator stimulus writes.
This is SIM_ONLY evidence; original motor strict rotor gate stays OPEN.
"""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from g0_memory import QTest
from tools.sitl_autonomous_transport import AUTO_BASE, REG, read_auto

MOTOR_BASE = 0x5ffeb000
MOTOR_MAGIC = 0x4d323645
PWM_HISTORY_BASE = 0x5ffe7000
PWM_HISTORY_MAGIC = 0x48323645
DMA_BASE = 0x40021000  # Native DMA0 register window
ARCH_BASE = 0x5ffe3000  # Existing read-only QEMU G11 architecture observer
OC_SOURCE_BASE = 0x5ffe5000
MCPWM_BASE = 0x40014000
ORIGINAL_SHA = "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"


def _configure_autonomous_dshot(qtest, *, arm_ms, drive_ms, coast_ms,
                                drive_permille):
    """PA26 input only; never program Guest registers."""
    get = lambda key: qtest.read(AUTO_BASE+REG[key])
    put = lambda key, val: qtest.write(AUTO_BASE+REG[key], val)
    if get("magic") != 0x41323645 or get("abi_version") != 4:
        raise RuntimeError("G13B7 original autonomous DShot engine absent")
    stages = [
        (arm_ms, 0, 0, 1),
        (drive_ms, drive_permille, drive_permille, 1),
        (coast_ms, 0, 0, 1),
    ]
    put("command", 3)
    put("stage_count", len(stages))
    for i, (duration, start, end, update) in enumerate(stages):
        put("stage_index", i)
        for key, val in (("duration_ms", duration),
                         ("start_permille", start),
                         ("end_permille", end), ("update_ms", update)):
            put(key, val)
            if get(key) != val:
                raise RuntimeError("DShot input staging readback changed")
    put("max_frames", 0)
    put("command", 1)
    return sum(stage[0] for stage in stages)


def _motor_snapshot(qtest):
    if qtest.read(MOTOR_BASE) != MOTOR_MAGIC:
        raise RuntimeError("Native QEMU motor not compiled or not opt-in enabled")
    get = lambda offset: qtest.read(MOTOR_BASE+offset)
    signed = lambda v: (v if v < 0x80000000 else v-0x100000000)
    return {
        "status_flags": get(0x04),
        "native_1us_physics_ticks": get(0x08),
        "actual_pwm_event_notifications": get(0x0c),
        "analog_phase_code_updates": get(0x10),
        "model_fault": get(0x14),
        "actual_pwm_six_bit_mask": get(0x18),
        "analog_codes": [get(0x1c),get(0x20),get(0x24)],
        "last_integrated_virtual_ns": get(0x28)|(get(0x2c)<<32),
        "model_rpm_integer": signed(get(0x30)),
        "electrical_milli_degrees_signed": signed(get(0x34)),
    }


def _pwm_source_snapshot(qtest):
    """Non-silicon read-only QEMU edge/clock journal, NOT duty estimates."""
    base = PWM_HISTORY_BASE
    get = lambda off: qtest.read(base+off)
    if get(0x00) != PWM_HISTORY_MAGIC:
        raise RuntimeError("Original QEMU clocked MCPWM history unavailable")
    flags = get(0x04)
    records = get(0x10)
    result = {
        "running": bool(flags & 1),
        "evaluator_valid": bool(flags & 2),
        "ring_dropped": bool(flags & 4),
        "actual_clocked_journal": bool(flags & 8),
        "records_retained": records,
        "total_events": get(0x14) | get(0x18) << 32,
        "dropped_events": get(0x1c) | get(0x20) << 32,
        "instantaneous_six_pad_mask": get(0x24),
        "native_pwm_zero_callbacks": get(0x28),
        "native_pwm_invalid_level_events": get(0x40),
    }
    if records:
        aux = get(0x80+(records-1)*32+0x1c)
        result["last_journal_gate_word"] = aux & 0x0f
        result["last_journal_trip_bits"] = (aux >> 9) & 3
        result["last_journal_level_valid"] = bool(aux & 0x10000)
    return result


def _receiver_snapshot(read32):
    """Read existing hardware and CPU debug viewports; never pause CPU.

    DMA0 CH2 address offsets below are the original QEMU G7 register bank,
    not invented application SRAM addresses. G11 is read-only by design.
    These reads are asynchronous diagnostic observations, not atomic state.
    """
    def dma(off):
        return read32(DMA_BASE+off)
    def arch(off):
        return read32(ARCH_BASE+off)
    def signed(value):
        return value if value < 0x80000000 else value-0x100000000
    if arch(0x00) != 0x47313101:
        raise RuntimeError("Native G11 read-only CPU observer missing")
    return {
        "dma_irq_mask": dma(0x028),
        "dma_irq_raw": dma(0x030),
        "dma_irq_masked": dma(0x038),
        "dma_ch2_trigger": dma(0x118),
        "dma_ch2_control": dma(0x220),
        "dma_ch2_source": dma(0x224),
        "dma_ch2_destination": dma(0x228),
        "dma_ch2_remaining": dma(0x22c),
        "cpu_exception_ipsr": arch(0x1c),
        "cpu_pc": arch(0x24),
        "cpu_lr": arch(0x20),
        "cpu_xpsr": arch(0x28),
        "cpu_primask": arch(0x04),
        "cpu_basepri": arch(0x08),
        "cpu_faultmask": arch(0x0c),
        "cpu_control": arch(0x10),
        "gpio_pa26_external": read32(0x5ffe0000),
        "gpio_pa26_capture_total": read32(0x5ffe0008),
        "gpio_pa26_dma_beat_total": read32(0x5ffe000c),
        "native_ost_latched": read32(OC_SOURCE_BASE+0x14),
        "native_oc_adc_codes": [read32(OC_SOURCE_BASE+4*i) for i in range(3)],
        "native_pwm_trip_latch": read32(MCPWM_BASE+0xb0),
    }


def _classify_receive_path(autonomous, original_guest, receiver):
    """Describe an observed halt of input delivery, not its root cause."""
    reasons=[]
    frames=autonomous["sent"]
    capture=autonomous["pa26_capture"]
    beats=autonomous["pa26_dma"]
    feeds=original_guest.get("valid_frame_feeds")
    if frames > 64 and capture >= 64 and beats <= 32:
        reasons.append("DMA_CH2_ONLY_ONE_FRAME_OR_LESS_DESPITE_PA26_EDGES")
    if frames > 64 and feeds == 0:
        reasons.append("ORIGINAL_GUEST_NO_VALID_DSHOT_FRAME")
    if beats == 32 and receiver["dma_ch2_remaining"] == 0:
        reasons.append("DMA_CH2_FIRST_BUFFER_EXHAUSTED_NOT_REARMED_AT_SAMPLE")
    if receiver["dma_irq_masked"]:
        reasons.append("DMA0_IRQ_PENDING_MASKED_STATUS_NONZERO_AT_SAMPLE")
    if receiver["cpu_exception_ipsr"] in (3, 4, 5, 6):
        reasons.append("GUEST_CPU_IN_FAULT_EXCEPTION_AT_SAMPLE")
    if receiver["native_ost_latched"]:
        reasons.append("NATIVE_POWER_TRIP_LATCHED_AT_SAMPLE")
    return reasons


def _wiring_failure_reasons(autonomous, motor, pwm):
    """Pinpoint missing stages; original fail-closed assertion is unchanged."""
    reasons = []
    if not autonomous["pa26_capture"] or not autonomous["pa26_dma"]:
        reasons.append("ORIGINAL_PA26_TIMG4_DMA_INPUT_NOT_SEEN")
    if not pwm["running"] or not pwm["native_pwm_zero_callbacks"]:
        reasons.append("NATIVE_MCPWM_CARRIER_NOT_RUNNING")
    if not pwm["total_events"]:
        reasons.append("NO_NATIVE_PWM_HISTORY_EVENTS")
    if not pwm["evaluator_valid"] or pwm["native_pwm_invalid_level_events"]:
        reasons.append("NATIVE_PWM_AQ_DB_PROVENANCE_INVALID")
    if not motor["actual_pwm_event_notifications"]:
        reasons.append("NATIVE_MOTOR_NOT_NOTIFIED_OF_PWM")
    if not motor["native_1us_physics_ticks"]:
        reasons.append("NATIVE_MOTOR_VIRTUAL_TIME_NOT_STARTED")
    if not motor["analog_phase_code_updates"]:
        reasons.append("NATIVE_BEMF_NEVER_PUBLISHED")
    if motor["model_fault"] or motor["status_flags"] & 4:
        reasons.append("NATIVE_MOTOR_FAIL_CLOSED")
    return reasons


def _read_original_guest_telemetry(qtest, symbol_addrs):
    """Read-only original SRAM through QTest; no CPU stop and no writes."""
    return {k:qtest.read(v) for k,v in symbol_addrs.items()}


_GUEST_DIAGNOSTIC_SYMBOLS = (
    "throt", "valid_frame_feeds", "step", "armed",
    "captured_events", "rejected_events", "scheduled", "serviced",
    "calibration_done", "runtime_aq_updates",
    "runtime_pwm_updates", "runtime_commit_count",
)


def _resolve_unambiguous_guest_symbols(nm_output):
    """Only optional, uniquely addressable original SRAM values are readable.

    Several C file-static variables (e.g. 'armed') share names in the
    original Rel17.3 ELF. Guessing one of those addresses would mislabel
    Guest telemetry. Exclude ambiguous entries without affecting native
    PWM, motor, DShot, or strict evidence gates.
    """
    import re
    import collections
    addresses = collections.defaultdict(set)
    pattern = re.compile(
        r"([0-9a-fA-F]{8,16})\s+([bBdD])\s+([A-Za-z_][A-Za-z0-9_]*)"
    )
    for row in nm_output.splitlines():
        m = pattern.fullmatch(row.strip())
        if not m or m[3] not in _GUEST_DIAGNOSTIC_SYMBOLS:
            continue
        addr = int(m[1], 16)
        if 0x20000000 <= addr < 0x20020000:
            addresses[m[3]].add(addr)
    unique = {name: next(iter(locations))
              for name, locations in addresses.items()
              if len(locations) == 1}
    unavailable = {
        name: ("AMBIGUOUS_STATIC_ELF_SYMBOL" if len(addresses[name]) > 1
               else "ORIGINAL_ELF_SYMBOL_NOT_AVAILABLE")
        for name in _GUEST_DIAGNOSTIC_SYMBOLS
        if name not in unique
    }
    return unique, unavailable


def _guest_symbol_addresses(elf):
    """Resolve read-only Guest SRAM diagnostics; ambiguous is not fatal."""
    output = subprocess.run(
        ["arm-none-eabi-nm", "-n", str(elf)],
        capture_output=True, text=True, check=True, timeout=15
    ).stdout
    return _resolve_unambiguous_guest_symbols(output)


def run(args):
    import hashlib
    observed = hashlib.sha256(args.elf.read_bytes()).hexdigest()
    if observed != ORIGINAL_SHA:
        raise RuntimeError("Pinned original ESCape32 Rel17.3 ELF SHA mismatch")
    if not args.cfg_flash.is_file():
        raise FileNotFoundError(args.cfg_flash)
    symbol_addrs, unresolved_guest_symbols = _guest_symbol_addresses(args.elf)
    with tempfile.TemporaryDirectory(prefix="e62-native-no-wfi-") as td:
        tmp = Path(td)
        sockpath = tmp/"qtest.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(sockpath))
            listener.listen(1)
            listener.settimeout(20)
            cmd = [
                str(args.qemu.resolve()), "-M",
                "am13e23019,esc-sim=on,esc-sim-native-motor=on,"
                "esc-sim-nfault-asserted=off",
                "-kernel", str(args.elf.resolve()),
                "-display", "none", "-serial", "none", "-monitor", "none",
                "-qtest", f"unix:path={sockpath}",
                "-icount", "shift=2,sleep=off,align=off",
                "-device", "loader,file="+str(args.cfg_flash.resolve())+
                           ",addr=0x4000,force-raw=on",
            ]
            # Deliberately NO -S, -gdb, RSP, CPU halt or WFI breakpoints.
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE)
            evidence = {
                "status": "OPEN_NATIVE_AUTONOMOUS_CLOSED_LOOP_NOT_STRICT_PASS",
                "original_elf_sha256": observed,
                "host_guest_register_writes": False,
                "used_guest_wfi_or_gdb": False,
                "motor_mode": "QEMU_VIRTUAL_CLOCK_NATIVE_ECX87_KV147_SIM_ONLY",
                "synthetic_timed_bemf_enabled": False,
                "physical_motor_qualified": False,
                "readable_original_guest_diagnostics": sorted(symbol_addrs),
                "unavailable_original_guest_diagnostics": unresolved_guest_symbols,
            }
            try:
                conn, _ = listener.accept()
                with conn:
                    qtest = QTest(conn)
                    evidence["motor_before"] = _motor_snapshot(qtest)
                    evidence["pwm_source_before"] = _pwm_source_snapshot(qtest)
                    evidence["original_guest_before"] = _read_original_guest_telemetry(qtest,symbol_addrs)
                    evidence["receiver_before"] = _receiver_snapshot(qtest.read)
                    evidence["runtime_diagnostics_by_stage"] = []
                    evidence["configured_dshot_frames"] = _configure_autonomous_dshot(
                        qtest, arm_ms=args.arm_ms, drive_ms=args.drive_ms,
                        coast_ms=args.coast_ms,
                        drive_permille=args.drive_permille)
                    deadline = time.monotonic() + args.wall_timeout_s
                    last = None
                    while time.monotonic() < deadline:
                        if proc.poll() is not None:
                            raise RuntimeError("QEMU exited during autonomous motor test")
                        auto = read_auto(qtest.read)
                        motor = _motor_snapshot(qtest)
                        last = dict(autonomous_dshot=auto, native_motor=motor)
                        if (not evidence["runtime_diagnostics_by_stage"] or
                                auto["stage"] != evidence["runtime_diagnostics_by_stage"][-1]["stage"]):
                            evidence["runtime_diagnostics_by_stage"].append({
                                "stage": auto["stage"],
                                "sent_frames":auto["sent"],
                                "virtual_elapsed_ns": auto["elapsed_ns"],
                                "original_guest":_read_original_guest_telemetry(qtest,symbol_addrs),
                                "pwm_source":_pwm_source_snapshot(qtest),
                                "native_motor":motor,
                                "receiver_and_cpu": _receiver_snapshot(qtest.read),
                            })
                        if auto["status"] & 4:
                            raise RuntimeError("Autonomous PA26 DShot timer failed: "+
                                               str(auto["error"]))
                        if motor["model_fault"] or motor["status_flags"] & 4:
                            raise RuntimeError("Native motor fail-closed: "+
                                               str(motor["model_fault"]))
                        if auto["status"] & 2:
                            break
                        time.sleep(.02)
                    else:
                        raise TimeoutError("QEMU autonomous virtual clock did not finish")
                    evidence.update(last)
                    evidence["pwm_source_after"] = _pwm_source_snapshot(qtest)
                    evidence["original_guest_after"] = _read_original_guest_telemetry(qtest,symbol_addrs)
                    evidence["receiver_after"] = _receiver_snapshot(qtest.read)
                    evidence["receiver_failure_reasons"] = _classify_receive_path(
                        auto,evidence["original_guest_after"],evidence["receiver_after"])
                    evidence["wiring_failure_reasons"] = _wiring_failure_reasons(
                        auto,motor,evidence["pwm_source_after"])
                    print("E62_NATIVE_AUTONOMOUS_SOURCE_COUNTS "+
                          json.dumps({
                              "auto":auto,
                              "motor":motor,
                              "pwm":evidence["pwm_source_after"],
                              "original_guest":evidence["original_guest_after"],
                              "wiring_failure_reasons":evidence["wiring_failure_reasons"],
                              "receiver_and_cpu":evidence["receiver_after"],
                              "receiver_failure_reasons":evidence["receiver_failure_reasons"],
                          },sort_keys=True),flush=True)
                    evidence["real_original_guest_cap1_observed_sim_only"] = (
                        qtest.read(AUTO_BASE+REG["trace_cap1_events"]))
                    evidence["real_timg12_zero_irq_observed_sim_only"] = (
                        qtest.read(AUTO_BASE+REG["trace_timg12_irq_events"]))
                    # Synthetic timed BEMF timer must never fire in this mode.
                    evidence["legacy_synthetic_bemf_callbacks"] = (
                        auto["bemf_timer_callbacks"])
                    if auto["bemf_timer_callbacks"] != 0:
                        raise AssertionError("Artificial BEMF generator leaked into native mode")
                    if auto["sent"] != evidence["configured_dshot_frames"]:
                        raise AssertionError("Not all autonomous DShot inputs delivered")
                    if evidence["receiver_failure_reasons"] and (
                        auto["sent"] > 64 and
                        evidence["original_guest_after"].get("valid_frame_feeds") == 0):
                        raise AssertionError("Original Guest DShot receiver did not rearm/accept frames: "+
                                             ",".join(evidence["receiver_failure_reasons"]))
                    if motor["native_1us_physics_ticks"] == 0 or (
                            motor["actual_pwm_event_notifications"] == 0 or
                            motor["analog_phase_code_updates"] == 0):
                        raise AssertionError(
                            "No source-clocked PWM motor BEMF coupling: "+
                            ",".join(evidence["wiring_failure_reasons"]))
                    evidence["status"] = (
                        "PASS_NATIVE_AUTONOMOUS_WIRING_SMOKE_SIM_ONLY_"
                        "STRICT_STABILITY_STILL_OPEN")
            except Exception as exc:
                evidence["status"] = "FAIL_NATIVE_AUTONOMOUS_WIRING_SMOKE"
                evidence["exception"] = type(exc).__name__+": "+str(exc)
                print("E62_NATIVE_AUTONOMOUS_NO_WFI_FAIL "+
                      json.dumps(evidence,sort_keys=True),flush=True)
                raise
            finally:
                args.artifact.parent.mkdir(parents=True,exist_ok=True)
                args.artifact.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n")
                if proc.poll() is None:
                    proc.terminate()
                try:
                    _, stderr = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    _, stderr = proc.communicate()
                args.artifact.with_suffix(".qemu.log").write_bytes(stderr)
            return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--cfg-flash", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, default=Path(
        "artifacts/e62-autonomous-native-motor-smoke.json"))
    parser.add_argument("--arm-ms",type=int,default=400)
    parser.add_argument("--drive-ms",type=int,default=250)
    parser.add_argument("--coast-ms",type=int,default=100)
    parser.add_argument("--drive-permille",type=int,default=200)
    parser.add_argument("--wall-timeout-s",type=int,default=120)
    args = parser.parse_args()
    if (not 300<=args.arm_ms<=5000 or
        not 10<=args.drive_ms<=3000 or
        not 10<=args.coast_ms<=3000 or
        not 1<=args.drive_permille<=1000 or
        not 10<=args.wall_timeout_s<=600):
        parser.error("Explicit, bounded virtual timing required")
    evidence=run(args)
    print("E62_NATIVE_AUTONOMOUS_NO_WFI_PROBE "+
          json.dumps(evidence,sort_keys=True))


if __name__=="__main__":
    main()
