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
from tools.native_dshot_scenario import load_native_scenario
from tools.native_p1_fault_plan import load_fault_plan

MOTOR_BASE = 0x5ffeb000
MOTOR_MAGIC = 0x4d323645
PWM_HISTORY_BASE = 0x5ffe7000
PWM_HISTORY_MAGIC = 0x48323645
DMA_BASE = 0x40021000  # Native DMA0 register window
ARCH_BASE = 0x5ffe3000  # Existing read-only QEMU G11 architecture observer
OC_SOURCE_BASE = 0x5ffe5000
MCPWM_BASE = 0x40014000
ORIGINAL_SHA = "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"




class TimedAutonomousQTest(QTest):
    """Original QTest protocol with per-command forensic provenance.

    The original common QTest defaults to a 5s socket deadline; that
    timeout corrupts the buffered stream and must NOT be retried.
    This subclass never mutates emulator time, CPU, or Guest state.
    """
    def __init__(self, sock, *, response_timeout_s):
        super().__init__(sock)
        self.sock.settimeout(response_timeout_s)
        self.last_command_started = None
        self.last_command_completed = None
        self.last_command_failed = None
        self.inflight_command = None
        self.max_successful_command_wall_s = 0.0
        self.command_started_at = 0.0

    def cmd(self, command):
        self.inflight_command = command
        self.command_started_at = time.monotonic()
        self.last_command_started = command
        try:
            response = super().cmd(command)
            self.last_command_completed = command
            self.max_successful_command_wall_s = max(
                self.max_successful_command_wall_s,
                time.monotonic()-self.command_started_at)
            return response
        except Exception as exc:
            self.last_command_failed = {
                "command": command,
                "exception": type(exc).__name__+": "+str(exc),
                "elapsed_wall_s": round(
                    time.monotonic()-self.command_started_at,3)
            }
            raise
        finally:
            self.inflight_command = None


def _autonomous_liveness(read32):
    """Constant-cost asynchronous monitor, not a synchronized snapshot."""
    r = lambda k: read32(AUTO_BASE+REG[k])
    return {
        "status": r("status"),
        "sent": r("sent"),
        "stage": r("stage"),
    }


def _continuous_dshot_stages(*, neutral_ms, ramp_ms, hold_ms, coast_ms,
                             drive_permille, ramp_update_ms):
    """External flight-controller profile, entirely independent of Guest.

    Every millisecond sends one DShot600 frame, including during
    original firmware boot/ARM. Zero is DShot DISARM/neutral; the QEMU
    G13B7 fixture maps nonzero permille to DShot active throttle 48..2047.
    Ramp must be exactly representable by the fixture's integer step ABI.
    """
    if not 300 <= neutral_ms <= 120000:
        raise ValueError("Neutral duration must cover realistic cold boot")
    if not 100 <= ramp_ms <= 120000:
        raise ValueError("Ramp duration outside bounded fixture range")
    if not 10 <= hold_ms <= 120000 or not 10 <= coast_ms <= 120000:
        raise ValueError("Hold/coast duration outside bounded fixture range")
    if not 1 <= drive_permille <= 1000:
        raise ValueError("Active DShot ramp endpoint out of range")
    if (not 1 <= ramp_update_ms <= ramp_ms or
            ramp_ms % ramp_update_ms or
            (drive_permille * ramp_update_ms) % ramp_ms):
        raise ValueError("Ramp updates not exactly representable at 0.1%")
    return [
        (neutral_ms, 0, 0, 1),
        (ramp_ms, 0, drive_permille, ramp_update_ms),
        (hold_ms, drive_permille, drive_permille, 1),
        (coast_ms, 0, 0, 1),
    ]


def _configure_autonomous_dshot(qtest, *, neutral_ms, ramp_ms,
                                hold_ms, coast_ms, drive_permille,
                                ramp_update_ms, scenario_stages=None,
                                external_fault=None, max_frames=0):
    """Stage PA26 traffic; optional bounded abrupt external FC disconnect."""
    get = lambda key: qtest.read(AUTO_BASE+REG[key])
    put = lambda key, val: qtest.write(AUTO_BASE+REG[key], val)
    if get("magic") != 0x41323645 or get("abi_version") != 4:
        raise RuntimeError("G13B7 original autonomous DShot engine absent")
    stages = (scenario_stages if scenario_stages is not None else
              _continuous_dshot_stages(
                  neutral_ms=neutral_ms, ramp_ms=ramp_ms, hold_ms=hold_ms,
                  coast_ms=coast_ms, drive_permille=drive_permille,
                  ramp_update_ms=ramp_update_ms))
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
    total = sum(stage[0] for stage in stages)
    if max_frames and not (0 < max_frames < total):
        raise ValueError("Link loss must stop before the last scenario frame")
    put("max_frames", max_frames)
    if external_fault is not None:
        # Physical PA22 input calendar ONLY; QEMU timer asserts and
        # releases the external pin at exact 1ms DShot frame boundaries.
        for offset,value in (
            (0x120,external_fault["assert_frame"]),
            (0x124,external_fault["release_frame"]),
            (0x128,1),
        ):
            qtest.write(AUTO_BASE+offset,value)
            if qtest.read(AUTO_BASE+offset)!=value:
                raise RuntimeError("Native external nFAULT plan readback failed")
    put("command", 1)
    return max_frames if max_frames else total


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
        "native_oc_publications":get(0x38),
        "ost3_latch_activations":get(0x3c),
        "first_ost3_cpu_pc":get(0x40),
        "first_ost3_virtual_ns":get(0x44)|(get(0x48)<<32),
        "first_ost3_valid_phase_mask":get(0x4c),
        "first_ost3_comparator_ready_mask":get(0x50),
        "first_ost3_comparator_trip_mask":get(0x54),
        "first_ost3_trip3_xbar_route":get(0x58),
        "first_ost3_tzsel":get(0x5c),
        "first_ost3_oc_codes":[get(0x60),get(0x64),get(0x68)],
        "first_ost3_dac_codes":[get(0x6c),get(0x70),get(0x74)],
        "first_ost3_hp_mux":get(0x78),
        "first_ost3_cpu_primask":get(0x7c),
        "first_ost3_cpu_ipsr":get(0x80),
        "first_ost3_prior_tz_flags":get(0x84),
        "first_ost3_trip3_xbar_invert":get(0x88),
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


def _receiver_ready_reasons(receiver, guest):
    """Diagnostic-only state report, NEVER gates continuous DShot.

    External flight controllers transmit neutral regardless of whether
    receiver boot has reached ARM. State is useful evidence, not a
    permission to start physical wire traffic.
    """
    reasons=[]
    if receiver["cpu_primask"] != 0:
        reasons.append("ORIGINAL_CPU_INTERRUPT_MASKED")
    if receiver["cpu_exception_ipsr"] in (3,4,5,6):
        reasons.append("ORIGINAL_CPU_FAULT_EXCEPTION")
    if receiver["dma_ch2_trigger"] & 0x7f != 34:
        reasons.append("ORIGINAL_DMA_CH2_TRIGGER_NOT_TIMG4")
    if receiver["dma_ch2_control"] & 2 == 0:
        reasons.append("ORIGINAL_DMA_CH2_DISABLED")
    if receiver["dma_ch2_remaining"] != 32:
        reasons.append("ORIGINAL_DMA_CH2_NOT_FRESH_32_BEATS")
    if receiver["dma_irq_raw"] & (1<<24):
        reasons.append("ORIGINAL_DMA_ADDRESS_FAULT")
    if guest.get("throt") != 1:
        reasons.append("ORIGINAL_NEUTRAL_ARM_WINDOW_NOT_ENTERED")
    if any((code & 0x10000) == 0 for code in receiver["native_oc_adc_codes"]):
        reasons.append("NATIVE_CURRENT_SENSE_NOT_VALID_AFTER_RESET")
    return reasons



def _wiring_failure_reasons(autonomous, motor, pwm):
    """Pinpoint missing stages; original fail-closed assertion is unchanged."""
    reasons = []
    if not autonomous["pa26_capture"] or not autonomous["pa26_dma"]:
        reasons.append("ORIGINAL_PA26_TIMG4_DMA_INPUT_NOT_SEEN")
    # Final-stage throttle is deliberately DShot=0. A stopped carrier
    # at teardown is EXPECTED, not proof that PWM never ran. Keep the
    # fail-closed test on source-owned zero-callback history instead.
    if not pwm["native_pwm_zero_callbacks"]:
        reasons.append("NATIVE_MCPWM_CARRIER_NEVER_CLOCKED")
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
    scenario_stages, scenario_meta = load_native_scenario(args.scenario)
    external_fault=(load_fault_plan(args.fault_scenario,scenario_stages)
                    if args.fault_scenario else None)
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
                "esc-sim-nfault-asserted=off" +
                (",esc-sim-wwdt-bootrst=on"
                 if getattr(args,"link_loss_last_frame",0) else ""),
                "-kernel", str(args.elf.resolve()),
                "-display", "none", "-serial", "none", "-monitor", "none",
                "-qtest", f"unix:path={sockpath}",
                "-icount", "shift=2,sleep=off,align=off",
                "-device", "loader,file="+str(args.cfg_flash.resolve())+
                           ",addr=0x4000,force-raw=on",
            ]
            # Deliberately NO -S, -gdb, RSP, CPU halt or WFI breakpoints.
            # A child whose stderr is never drained can block on a full
            # pipe, freezing its QTest responses independently of QEMU
            # virtual timer correctness. A regular file is non-blocking
            # with respect to a bounded pipe buffer and survives failure.
            qemu_log_path = args.artifact.with_suffix(".qemu.log")
            qemu_log_path.parent.mkdir(parents=True,exist_ok=True)
            qemu_log_handle = qemu_log_path.open("wb")
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                        stderr=qemu_log_handle)
            except BaseException:
                qemu_log_handle.close()
                raise
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
            run_wall_started = time.monotonic()
            try:
                conn, _ = listener.accept()
                with conn:
                    qtest = TimedAutonomousQTest(
                        conn, response_timeout_s=args.qtest_response_timeout_s)
                    evidence["motor_before"] = _motor_snapshot(qtest)
                    evidence["pwm_source_before"] = _pwm_source_snapshot(qtest)
                    evidence["original_guest_before"] = _read_original_guest_telemetry(qtest,symbol_addrs)
                    evidence["receiver_before"] = _receiver_snapshot(qtest.read)
                    evidence["runtime_diagnostics_by_stage"] = []
                    # Flight-controller role: transmit real DShot600 from
                    # boot onward. Guest DMA/IRQ/ARM states are observations,
                    # never a readiness gate for the external wire source.
                    evidence["initial_receiver_diagnostic_only"] = (
                        _receiver_ready_reasons(
                            evidence["receiver_before"],
                            evidence["original_guest_before"]))
                    evidence["dshot_profile"] = {
                        "source":"INDEPENDENT_EXTERNAL_FLIGHT_CONTROLLER",
                        "frame_period_ns":1000000,
                        "continuous_from_initial_stimulus":True,
                        "original_receiver_ready_not_a_start_condition":True,
                        "neutral_ms":args.arm_ms,
                        "ramp_ms":args.drive_ms,
                        "hold_ms":args.hold_ms,
                        "coast_ms":args.coast_ms,
                        "ramp_update_ms":args.ramp_update_ms,
                        "target_permille":args.drive_permille,
                    }
                    evidence["native_dshot_scenario"] = scenario_meta
                    evidence["native_external_fault_plan"] = external_fault
                    evidence["configured_dshot_frames"] = _configure_autonomous_dshot(
                        qtest, neutral_ms=args.arm_ms, ramp_ms=args.drive_ms,
                        hold_ms=args.hold_ms, coast_ms=args.coast_ms,
                        drive_permille=args.drive_permille,
                        ramp_update_ms=args.ramp_update_ms,
                        scenario_stages=scenario_stages,
                        external_fault=external_fault,
                        max_frames=getattr(args,"link_loss_last_frame",0))
                    deadline = time.monotonic() + args.wall_timeout_s
                    last_stage = None
                    previous_sent = -1
                    last_advance_wall = time.monotonic()
                    last_progress_bucket = -1
                    # Only three MMIO reads per routine poll; no WFI/GDB
                    # and no dozens of asynchronous Guest/peripheral reads
                    # at every 20ms host iteration. Stage diagnostics are
                    # optional observations and never gate physical input.
                    while time.monotonic() < deadline:
                        if proc.poll() is not None:
                            raise RuntimeError("QEMU exited during autonomous motor test")
                        poll = _autonomous_liveness(qtest.read)
                        evidence["last_successful_dshot_poll"] = poll
                        if poll["sent"] != previous_sent:
                            last_advance_wall = time.monotonic()
                            previous_sent = poll["sent"]
                        bucket = poll["sent"] // 250
                        if bucket > last_progress_bucket:
                            last_progress_bucket = bucket
                            print("E62_NATIVE_DSHOT_LIVENESS "+
                                  json.dumps(poll,sort_keys=True),flush=True)
                        if poll["stage"] != last_stage:
                            evidence["runtime_diagnostics_by_stage"].append({
                                "stage":poll["stage"],
                                "sent_frames":poll["sent"],
                                "monitor_only":True,
                            })
                            last_stage = poll["stage"]
                        if poll["status"] & 4:
                            error_code = qtest.read(AUTO_BASE+REG["error"])
                            raise RuntimeError("Native autonomous DShot source "
                                               "failed code="+str(error_code))
                        if poll["status"] & 2:
                            break
                        # Report a virtual-time/progress stall as a separate
                        # failure from an MMIO socket response timeout.
                        if time.monotonic()-last_advance_wall > args.stall_wall_timeout_s:
                            raise TimeoutError(
                                "DShot source progress stalled while QTest "
                                "remained responsive: "+json.dumps(poll))
                        time.sleep(.15)
                    else:
                        raise TimeoutError(
                            "QEMU autonomous run exceeded wall timeout; "+
                            json.dumps(evidence.get("last_successful_dshot_poll")))
                    # Complete original-source diagnostics once per run.
                    # These are non-atomic read-only observations, not a
                    # source of physical model updates.
                    auto = read_auto(qtest.read)
                    motor = _motor_snapshot(qtest)
                    evidence.update(autonomous_dshot=auto,native_motor=motor)
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
                        raise AssertionError("Not all continuous DShot frames delivered")
                    if auto["target_frames"] != evidence["configured_dshot_frames"]:
                        raise AssertionError("Native external frame boundary mismatch")
                    if getattr(args,"link_loss_last_frame",0):
                        if auto["last_dshot"] == 0:
                            raise AssertionError(
                                "Link-loss test must stop on actual positive DShot")
                    elif auto["last_dshot"] != 0:
                        raise AssertionError(
                            "No full-length neutral-ramp-hold-neutral DShot")
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
                    if getattr(args,"link_loss_last_frame",0):
                        # P1: after QEMU's independent FC STOPS sending
                        # physical frames, keep the unhalted Guest running.
                        # Only READ WWDTSTAT; never service/modify its counter.
                        wwdt_run = 0x400d110c
                        running_before=qtest.read(wwdt_run)
                        evidence["link_loss_last_frame"]=auto["sent"]
                        evidence["link_loss_last_dshot"]=auto["last_dshot"]
                        evidence["link_loss_wwdt_running_on_disconnect"]=(
                            running_before==1)
                        if running_before != 1:
                            raise AssertionError(
                                "Original Guest WWDT not armed at signal loss")
                        deadline_loss=time.monotonic()+args.link_loss_wall_timeout_s
                        marker="ESC_SIM_WWDT_BOOTRST_REQUESTED:"
                        found=False
                        while time.monotonic()<deadline_loss:
                            if proc.poll() is not None:
                                raise RuntimeError(
                                    "QEMU exited during Original Guest input loss")
                            with qemu_log_path.open("rb") as log:
                                log.seek(0,2)
                                size=log.tell()
                                log.seek(max(0,size-16384))
                                tail=log.read().decode(
                                    "utf-8",errors="replace")
                            if marker in tail:
                                found=True
                                break
                            # Read-only WWDTSTATE keeps the QTest alive
                            # without altering a Guest-controlled timer.
                            evidence["link_loss_wwdt_last_running"]=(
                                qtest.read(wwdt_run)==1)
                            time.sleep(.20)
                        if not found:
                            raise TimeoutError(
                                "Real original Guest loss did not cause WWDT "
                                "BOOTRST in the bounded virtual timer test")
                        evidence["link_loss_bootrst_observed"]=True
                        evidence["link_loss_guest_writes"]=False
                        evidence["link_loss_original_firmware_unchanged"]=True
                    evidence["status"] = (
                        "OBSERVED_P1_EXTERNAL_NFAULT_NO_RECOVERY_CLAIM"
                        if external_fault is not None else
                        "OBSERVED_P1_GUEST_WWDT_INPUT_LOSS_SIM_ONLY"
                        if getattr(args,"link_loss_last_frame",0) else
                        "PASS_NATIVE_AUTONOMOUS_WIRING_SMOKE_SIM_ONLY_"
                        "STRICT_STABILITY_STILL_OPEN")
            except Exception as exc:
                evidence["status"] = "FAIL_NATIVE_AUTONOMOUS_WIRING_SMOKE"
                evidence["exception"] = type(exc).__name__+": "+str(exc)
                evidence["qemu_alive_at_failure"] = proc.poll() is None
                if "qtest" in locals():
                    evidence["qtest_last_command_started"] = (
                        qtest.last_command_started)
                    evidence["qtest_last_command_completed"] = (
                        qtest.last_command_completed)
                    evidence["qtest_last_command_failed"] = (
                        qtest.last_command_failed)
                    evidence["qtest_max_successful_command_wall_s"] = (
                        round(qtest.max_successful_command_wall_s,3))
                    # TimeoutError poisons the buffered socket stream;
                    # NEVER retry QTest readl on that same file object.
                    # This also prevents another misleading 5s hang.
                    if not isinstance(exc, (OSError,TimeoutError)):
                        try:
                            evidence["receiver_at_failure"] = (
                                _receiver_snapshot(qtest.read))
                            evidence["original_guest_at_failure"] = (
                                _read_original_guest_telemetry(qtest,symbol_addrs))
                        except Exception as diagnostic_exc:
                            evidence["failure_snapshot_error"] = (
                                type(diagnostic_exc).__name__+": "+str(diagnostic_exc))
                print("E62_NATIVE_AUTONOMOUS_NO_WFI_FAIL "+
                      json.dumps(evidence,sort_keys=True),flush=True)
                raise
            finally:
                evidence["qemu_run_wall_elapsed_s"] = round(
                    time.monotonic()-run_wall_started,6)
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                qemu_log_handle.flush()
                qemu_log_handle.close()
                # QTest may already have timed out, so retrieve asynchronous
                # source-owned trip evidence from the child process file.
                # Keep the entire original QEMU log as a separate artifact.
                # Retain entire P0 source event trace in a separate file
                # independently of JSON/QTest success. Host never invents
                # event timestamps, edges, sectors or rotor samples.
                p0_path=args.artifact.with_suffix(".p0.events.log")
                with qemu_log_path.open("r",errors="replace") as source, (
                        p0_path.open("w")) as trace:
                    event_count=0
                    for line in source:
                        if "E62_P0_EVENT " in line:
                            trace.write(line)
                            event_count+=1
                evidence["p0_event_trace_path"]=str(p0_path)
                evidence["p0_source_event_count"]=event_count
                evidence["qemu_log_bytes"]=qemu_log_path.stat().st_size
                log_tail = qemu_log_path.read_bytes()[-65536:].decode(
                    "utf-8",errors="replace")
                trip_events = [
                    line for line in log_tail.splitlines()
                    if "E62_NATIVE_FIRST_OST3 " in line
                ]
                evidence["qemu_stderr_log_path"] = str(qemu_log_path)
                evidence["source_latched_first_ost3_log"] = trip_events[-1:] 
                evidence["qemu_stderr_log_tail"] = log_tail[-4096:]
                evidence["qemu_exit_code_after_probe"] = proc.returncode
                args.artifact.parent.mkdir(parents=True,exist_ok=True)
                args.artifact.write_text(json.dumps(
                    evidence,indent=2,sort_keys=True)+"\n")
            return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--cfg-flash", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, default=Path(
        "artifacts/e62-autonomous-native-motor-smoke.json"))
    parser.add_argument("--scenario",type=Path,default=(
        Path(__file__).resolve().parents[1]/
        "scenarios/e62-native-p0-smoke.json"),
        help="Versioned external 1kHz DShot JSON; Guest readiness NEVER gates")
    parser.add_argument("--fault-scenario",type=Path,default=None,
                        help="Optional SIM_ONLY external PA22 nFAULT JSON "
                             "scheduled by QEMU virtual 1kHz clock; no "
                             "original Guest register/IRQ writes")
    parser.add_argument("--arm-ms",type=int,default=1500,
                        help="Continuous DShot=0 cold-boot/neutral stage")
    parser.add_argument("--drive-ms",type=int,default=1000,
                        help="Continuous linear throttle ramp duration")
    parser.add_argument("--hold-ms",type=int,default=300,
                        help="Continuous constant-throttle hold duration")
    parser.add_argument("--coast-ms",type=int,default=200,
                        help="Continuous DShot=0 final stage")
    parser.add_argument("--ramp-update-ms",type=int,default=5,
                        help="Native integer-permille throttle step interval")
    parser.add_argument("--drive-permille",type=int,default=200)
    parser.add_argument("--link-loss-last-frame",type=int,default=0,
                        help="P1 opt-in: stop external DShot source before "
                             "final neutral stage at this positive frame; "
                             "do not send any further wire commands")
    parser.add_argument("--link-loss-wall-timeout-s",type=int,default=180,
                        help="Bounded wall time for Guest WWDT to expire "
                             "after source stops; not virtual timeout")
    parser.add_argument("--wall-timeout-s",type=int,default=180)
    parser.add_argument("--qtest-response-timeout-s",type=int,default=20,
                        help="Individual QTest readl deadline, not a CPU halt")
    parser.add_argument("--stall-wall-timeout-s",type=int,default=30,
                        help="Fail if DShot sent counter is unchanged while responsive")
    args = parser.parse_args()
    if (not 30 <= args.wall_timeout_s <= 600 or
        not 30 <= args.link_loss_wall_timeout_s <= 360 or
        not 5 <= args.qtest_response_timeout_s <= 60 or
        not 5 <= args.stall_wall_timeout_s <= 120):
        parser.error("Explicit bounded wall/QTest/progress timeouts required")
    try:
        _continuous_dshot_stages(
            neutral_ms=args.arm_ms, ramp_ms=args.drive_ms,
            hold_ms=args.hold_ms, coast_ms=args.coast_ms,
            drive_permille=args.drive_permille,
            ramp_update_ms=args.ramp_update_ms)
    except ValueError as exc:
        parser.error(str(exc))
    if args.link_loss_last_frame and args.fault_scenario:
        parser.error("P1 input-loss and external PA22 fault tests must be separate")
    evidence=run(args)
    print("E62_NATIVE_AUTONOMOUS_NO_WFI_PROBE "+
          json.dumps(evidence,sort_keys=True))


if __name__=="__main__":
    main()
