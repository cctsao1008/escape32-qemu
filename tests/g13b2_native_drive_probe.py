#!/usr/bin/env python3
"""G13B2E EXPERIMENT: native SIM_ONLY DShot -> motor start -> gate evidence.

Never forge guest throttle/PWM/Gate/Trip/IRQ. QTest owns physical PA26
wire edges and three healthy external current samples ONLY. Firmware must
process the DShot CRC, execute motor_output_start(), survive trip preflight,
then call power_stage_enable() after real PWM zero events.

By default this is a bounded *diagnostic*, never a claimed PASS if native
actuation is not observed. --require-drive makes these conditions a strict
acceptance gate. Not a sensorless closed-loop or real-board safety claim.
"""
import argparse
from dataclasses import asdict
import json
import math
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
from g13b_native_dshot import queue_dshot600_wire, WAVE, PA26, DMA
from g13b2_native_safety import snapshot, verify, EXT_OC, PWM4
from tools.virtual_bldc import gate_and_pads_connected
from tools.native_pwm_qualification import observe_original_pwm
from tools.native_bldc_seed import one_native_pwm_period
from tools.native_bemf_qualification import (
    observe_original_bemf_route, audit_native_bemf_arm_elf
)
from tools.virtual_bldc import MotorParameters, VirtualBLDC
from tools.virtual_bldc_feedback import AnalogFrontend
from tools.native_runtime_timeline import (
    NativePwmTimeline, ECAP1_TSCTR, NATIVE_ECAP_CLOCK_HZ
)
from tools.native_bemf_injection import NativeBemfInjector
from tools.native_bemf_capture import prove_capture_from_native_samples
from tools.native_bemf_policy_audit import prove_original_early_rejection
from tools.native_bemf_timeout_qualification import (
    prove_native_no_feedback_timeout
)
from tools.native_timg12_observer import observe_native_timg12
from tools.native_pwm_deadband_diagnostic import native_deadband_source_clamp, read_native_deadband
from tools.native_power_coupled_plant import NativePowerCoupledBLDC
from tools.native_closed_loop_audit import NativeClosedLoopAudit
from tools.native_rotor_motion_audit import NativeRotorMotionAudit
from tools.native_power_path_qualification import qualify_cross_phase_bridge
from tools.virtual_bldc_feedback import SIM_BEMF_INPUT
from tools.sitl_trace import SitlTraceRecorder, file_sha256
from tools.sitl_live import SitlLiveServer

FAULT_FN = "am13e_app_motor_fault_reset"

def native_pa26_receiver_rearm_snapshot(qtest):
    """Read only TI DMA0 CH2 registers; never clear a DMA IRQ or re-arm it.

    A rejected wire packet cannot be counted as DShot CRC or 32-beat
    evidence. A later *new* physical frame is permitted only if ORIGINAL
    guest firmware has organically restarted CH2 with a fresh 32-word
    buffer and configured TIMG4 GEN_EVENT1 trigger #34.
    """
    base = DMA + 0x1000
    ctl = qtest.read(base + 0x220)
    remaining = qtest.read(base + 0x22c)
    trigger = qtest.read(base + 0x118) & 0xff
    raw = qtest.read(base + 0x030)
    return {
        "dma_ch2_control": hex(ctl),
        "dma_ch2_remaining": remaining,
        "dma_ch2_trigger": trigger,
        "dma_raw_irq": hex(raw),
        "source_owned_fresh_rx_buffer": bool(
            (ctl & 2) and remaining == 32 and trigger == 34
            and not (raw & (1 << 24))),
        "guest_register_writes": False,
    }






def native_original_zero_throttle_arm(rsp, qtest, *, wfi, hardfault,
                                     armed_breakpoints, throt,
                                     callback, slice_ms, runtime_slices,
                                     bemf_state):
    """Complete original ARM=1 250ms neutral by physical DShot600=0.

    Enter only at source-owned arming __WFI. The receiver must accept
    an actual physical PA26->TIMG4->DMA0->CRC packet and set original
    throt=0. Then the native 16kHz SysTick must truly elapse >=4000
    ticks and the original Rel17 main reaches its running-loop WFI.
    No fake Guest throttle, timer fast-forward, or bypass of ARM.
    """
    if len(wfi) != 2 or not wfi[0] < wfi[1]:
        raise AssertionError(
            "Pinned original Rel17 WFI layout cannot locate arming vs run")
    before = rsp.mem32(throt)
    if ("valid_frame_feeds" not in bemf_state or
            "tick" not in bemf_state):
        raise AssertionError(
            "Original input watchdog and SysTick symbols required "
            "for strict physical CRC/ARM proof")
    valid_feeds_before = rsp.mem32(bemf_state["valid_frame_feeds"])
    if before != 1:
        raise AssertionError(
            "Expected source original ARM window to force throttle=1; "
            f"actual={before}")
    # PA26/DMA counters are cumulative; snapshot before EACH physical
    # packet and later verify exactly one 32-edge contribution.
    capture_start = qtest.read(PA26 + 0x08)
    dma_start = qtest.read(PA26 + 0x0c)
    # Stop at original actual callback, not a Host-created decoder.
    frame = queue_dshot600_wire(qtest, 0, allow_zero=True)
    if frame != 0:
        raise AssertionError("Not an actual DShot600 neutral packet")
    add_bp(rsp, callback)
    armed_breakpoints.add(callback)
    def sample_physical_neutral_ingress(n, state):
        # Observe physical PA26 input and DMA capture without touching
        # motor/Guest SRAM. Useful when callback never occurs.
        port = {
            "slice": n,
            "target_native_callback": hex(callback),
            "cpu_pc": hex(state["pc"]),
            "cpu_ipsr": state["ipsr"],
            "cpu_primask": state["primask"],
            "native_throt": rsp.mem32(throt),
            "wave_queued": qtest.read(WAVE + 0x08),
            "wave_delivered": qtest.read(WAVE + 0x0c),
            "wave_busy": qtest.read(WAVE + 0x10),
            "wave_pa26_transitions": qtest.read(PA26 + 0x04),
            "wave_pa26_capture": qtest.read(PA26 + 0x08),
            "wave_dma_beats": qtest.read(PA26 + 0x0c),
        }
        for name in ("tick", "cfg"):
            if name in bemf_state:
                address = bemf_state[name]
                if name == "cfg":
                    # Only original Cfg fields; map pinned src/common.h.
                    port["native_cfg_id"] = rsp.mem32(address) & 0xffff
                    port["native_cfg_freq_duty_28"] = hex(
                        rsp.mem32(address + 28))
                    port["native_cfg_rate_32"] = hex(
                        rsp.mem32(address + 32))
                    # Pinned src/common.h Cfg: input_mode byte +52,
                    # arm byte +20, from verified source ABI.
                    port["native_cfg_input_mode"] = (
                        rsp.mem32(address + 52) & 0xff)
                    port["native_cfg_arm"] = (
                        rsp.mem32(address + 20) & 0xff)
                else:
                    port["native_tick"] = rsp.mem32(address)
        return port

    def report_physical_ingress(n, state):
        if n == 1 or n % 4 == 0 or n == runtime_slices:
            print("G13B3N_ORIGINAL_NEUTRAL_RX_PROGRESS " +
                  json.dumps(sample_physical_neutral_ingress(n, state),
                             sort_keys=True), flush=True)

    # A DShot ESC is normally driven by a continuing physical neutral
    # signal during the original 250ms arming window. If the very first
    # complete pulse train was lost while the Guest receiver entered
    # its native RX state, resend a NEW physical zero packet. Neither
    # helper alters Guest DMA, throttle, vector, SysTick or ARM window.
    # The selected Rel17 receiver starts a genuine ~1 s WWDT.
    # Waiting twenty long host polling slices for the first undecoded
    # training packet advances several SECONDS of native SysTick time:
    # WWDT expires BEFORE a second, otherwise valid, zero packet can
    # feed it. Retry the actual physical wire promptly; do not reset,
    # pause, feed, or reconfigure the firmware watchdog.
    first_zero_tick = rsp.mem32(bemf_state["tick"])
    # Native CI evidence: two 80ms Host polls advanced up to 5228
    # actual 16kHz Guest ticks before a second physical zero packet.
    # That can consume the genuine input-WWDT window before the CRC
    # callback. Poll the already-scheduled PA26 wave in shorter bounded
    # intervals; no Guest clock or watchdog manipulation is permitted.
    neutral_poll_ms = min(slice_ms, 25)
    neutral_poll_slices = 2
    max_physical_zero_packets = 4
    for attempt in range(max_physical_zero_packets):
        if attempt:
            if (qtest.read(WAVE + 0x10) != 0 or
                    qtest.read(WAVE + 0x08) != 32 or
                    qtest.read(WAVE + 0x0c) != 32):
                raise AssertionError(
                    "Cannot requeue neutral while real PA26 waveform "
                    "is still busy or missing delivered wire edges")
            if qtest.read(WAVE + 0x14) != 0:
                raise AssertionError("Neutral PA26 must return low at frame end")
            capture_start = qtest.read(PA26 + 0x08)
            dma_start = qtest.read(PA26 + 0x0c)
            new_frame = queue_dshot600_wire(
                qtest, 0, allow_zero=True, reset_completed_wave=True)
            if new_frame != frame:
                raise AssertionError("Retransmitted genuine neutral mismatch")
            retry_tick = rsp.mem32(bemf_state["tick"])
            elapsed_native_ticks = (retry_tick - first_zero_tick) & 0xffffffff
            # This is a fail-closed deadline, NOT a simulated watchdog
            # feed. Keep retransmissions within the original selected
            # input WWDT period, nominally 16000 real 16kHz SysTicks.
            if elapsed_native_ticks >= 12000:
                raise AssertionError(
                    "G13B3N zero-DShot retransmission missed native "
                    "WWDT deadline; not authorized to recover expired "
                    f"watchdog: ticks={elapsed_native_ticks}")
            print("G13B3N_PHYSICAL_ZERO_DSHOT_RETRANSMISSION " +
                  json.dumps({"attempt": attempt + 1,
                              "frame": new_frame,
                              "previous_delivered": 32,
                              "elapsed_native_systick": elapsed_native_ticks,
                              "guest_writes": False}, sort_keys=True),
                  flush=True)
        try:
            resume_to(
                rsp, callback, hardfault, neutral_poll_ms,
                neutral_poll_slices,
                "G13B3N_NATIVE_NEUTRAL_DSHOT_CALLBACK",
                on_pause=report_physical_ingress)
            break
        except AssertionError as exc:
            print("G13B3N_NEUTRAL_RX_ATTEMPT_BLOCKER " +
                  json.dumps(
                      dict(attempt=attempt + 1, error=str(exc),
                           physical=sample_physical_neutral_ingress(
                               runtime_slices, observer(rsp))),
                      sort_keys=True), flush=True)
            # Only an actual callback timeout may be retried, and only
            # while a new physical packet can arrive BEFORE the native
            # input WWDT deadline. Never bypass original Rel17 ARM policy.
            # A fault or a lost/undelivered wire packet is terminal.
            if ("native guest did not reach" not in str(exc) or
                    attempt + 1 == max_physical_zero_packets):
                raise
    if (rsp.reg(0) & 0xffff) != 0:
        raise AssertionError("Original callback did not decode DShot neutral")
    captures = qtest.read(PA26 + 0x08)
    dma_beats = qtest.read(PA26 + 0x0c)
    delivered = qtest.read(WAVE + 0x0c)
    neutral_receipt = {
        "zero_packet_attempt": attempt + 1,
        "native_guest_frame_at_callback": rsp.reg(0) & 0xffff,
        "physical_wave_delivered_this_packet": delivered,
        "original_pa26_capture_total": captures,
        "original_pa26_capture_this_packet": captures - capture_start,
        "original_dma_beat_total": dma_beats,
        "original_dma_beats_this_packet": dma_beats - dma_start,
        "guest_writes": False
    }
    print("G13B3N_ORIGINAL_NATIVE_ZERO_RX_FRAME_CAUSAL_DELTA " +
          json.dumps(neutral_receipt, sort_keys=True), flush=True)
    if (delivered != 32 or
            captures - capture_start != 32 or
            dma_beats - dma_start != 32):
        raise AssertionError(
            "Latest neutral packet missing genuine 32 PA26/DMA edges: " +
            json.dumps(neutral_receipt, sort_keys=True))
    callback_tick = rsp.mem32(bemf_state["tick"])
    # Preserve the original native callback and IRQ return semantics.
    # A dynamically observed LR inside decoder/IRQ is not itself a
    # trustworthy replayable source location: verify the actual
    # firmware-owned CRC effect and 250ms ARM release at the ORIGINAL
    # normal-control WFI instead of fabricating or forcing a return.
    del_bp(rsp, callback)
    armed_breakpoints.remove(callback)
    add_bp(rsp, wfi[0])
    armed_breakpoints.add(wfi[0])
    normal = wait_for_native_main_wfi(
        rsp, (wfi[0],), hardfault, slice_ms,
        max_slices=max(runtime_slices, 72),
        stage="G13B3N_ORIGINAL_ZERO_THROTTLE_ARM_RELEASE")
    original_feeds_after = rsp.mem32(bemf_state["valid_frame_feeds"])
    original_throt_after = rsp.mem32(throt)
    original_tick_after = rsp.mem32(bemf_state["tick"])
    original_arm_elapsed = (
        original_tick_after - callback_tick) & 0xffffffff
    neutral_policy = {
        "original_valid_crc_feeds_before": valid_feeds_before,
        "original_valid_crc_feeds_after": original_feeds_after,
        "original_native_throt_after_arm": original_throt_after,
        "original_systick_at_zero_callback": callback_tick,
        "original_systick_at_run_wfi": original_tick_after,
        "elapsed_native_systick_after_callback": original_arm_elapsed,
        "minimum_native_arm_systick": 4000,
        "original_running_wfi_pc": hex(normal),
        "host_forged_throttle_timer_or_crc": False
    }
    print("G13B3N_ORIGINAL_ZERO_CRC_AND_250MS_ARM_RELEASE " +
          json.dumps(neutral_policy, sort_keys=True), flush=True)
    # Source am13e_app_io_dshot_packet feeds the watchdog only AFTER
    # dshotcrc() succeeds, then dshot_apply_packet(0) writes throt=0.
    # Source main.c enters wfi[0] only AFTER the unchanged arm window.
    if (original_feeds_after <= valid_feeds_before or
            original_throt_after != 0 or
            original_arm_elapsed < 4000 or
            original_arm_elapsed >= 0x80000000):
        raise AssertionError(
            "Native zero-DShot CRC or original 250ms ARM proof failed: " +
            json.dumps(neutral_policy, sort_keys=True))
    del_bp(rsp, wfi[0])
    armed_breakpoints.remove(wfi[0])
    # Caller supplies the following real 1500-throttle command only
    # after all 32 physical neutral edges have completed.
    if qtest.read(WAVE + 0x10) != 0:
        raise AssertionError("Neutral physical waveform remains active")
    return dict(qualified=True, physical_zero_frame=frame,
                physical_zero_edges=32, physically_sent_zero_packets=attempt+1,
                 original_packet_causal_delta=neutral_receipt,
                 original_crc_arm_policy=neutral_policy,
                 original_callback_crc_accepted=True,
                source_arm_window_released=True,
                native_original_run_wfi_pc=normal)


def resume_to(rsp, target, hardfault, slice_ms, slices, label,
              on_pause=None):
    for n in range(slices):
        stop, interrupted = continue_bounded(rsp, slice_ms)
        if not stop.startswith(("S02", "T02", "S05", "T05")):
            raise RuntimeError(f"{label} unexpected GDB stop {stop!r}")
        state = observer(rsp)
        if (state["pc"] == hardfault or state["cfsr"] or state["hfsr"]):
            raise AssertionError(f"{label} original firmware CPU fault: {state}")
        if interrupted and on_pause is not None:
            on_pause(n + 1, state)
        if not interrupted:
            if state["pc"] != target:
                raise AssertionError(
                    f"{label}: unexpected breakpoint 0x{state['pc']:08x}")
            return
    raise AssertionError(f"{label} native guest did not reach "
                         f"0x{target:08x} in {slices} bounded slices")


def trace_original_start_preconditions(rsp, symbols, armed,
                                       hardfault, slice_ms, max_slices):
    """Inspect actual native readiness return values; no guest mutations.

    Do not assume which guard rejected motor startup. Watch calls to
    the two separate original-ELF readiness functions, their real
    caller-return PCs and final motor_output_start return register.
    """
    original_return = rsp.reg(14) & ~1
    if not 0x6000 <= original_return < 0x80000:
        raise AssertionError("Original motor start LR outside app text")
    watched = ("am13e_app_motor_nfault_trip_ready",
               "am13e_app_motor_bemf_reference_start_ready")
    entrances = {symbols[name]: name for name in watched}
    pending = {}
    result = {}
    add_bp(rsp, original_return)
    armed.add(original_return)
    for addr in sorted(entrances):
        add_bp(rsp, addr)
        armed.add(addr)
    try:
        for i in range(max_slices * 8):
            stop, paused = continue_bounded(rsp, slice_ms)
            if not stop.startswith(("S02", "T02", "S05", "T05")):
                raise RuntimeError(f"Native start trace stop={stop!r}")
            cpu = observer(rsp)
            pc = cpu["pc"]
            if pc == hardfault or cpu["cfsr"] or cpu["hfsr"]:
                raise AssertionError(f"CPU fault during native start {cpu}")
            if paused:
                continue
            if pc == original_return:
                result["native_start_return"] = rsp.reg(0)
                print("G13B2E_NATIVE_START_FUNCTION_RETURNS " +
                      json.dumps(result, sort_keys=True), flush=True)
                return result
            if pc == symbols[FAULT_FN]:
                result["status"] = "FAULT_RESET_INSIDE_START"
                return result
            if pc in entrances:
                name = entrances[pc]
                lr = rsp.reg(14) & ~1
                if not 0x6000 <= lr < 0x80000 or lr in pending or lr == original_return:
                    raise AssertionError(f"Invalid native readiness return: {name}, {lr:x}")
                del_bp(rsp, pc)
                armed.remove(pc)
                add_bp(rsp, lr)
                armed.add(lr)
                pending[lr] = name
                result[name + "_called"] = 1
                continue
            if pc in pending:
                name = pending.pop(pc)
                result[name + "_return"] = rsp.reg(0)
                print(f"G13B2E_NATIVE_PRECONDITION {name} "
                      f"return_value={rsp.reg(0)}", flush=True)
                del_bp(rsp, pc)
                armed.remove(pc)
                continue
            raise AssertionError(f"Native start trace unexpected PC={pc:08x}")
        result["status"] = "START_TRACE_TIMEOUT"
        return result
    finally:
        for addr in (original_return, *entrances.keys(), *pending.keys()):
            if addr in armed:
                del_bp(rsp, addr)
                armed.remove(addr)


def native_symbol_location(elf, address):
    """Symbolize the actual CI-built SIM_ONLY ELF, never a reference map."""
    try:
        result = subprocess.run(
            ["arm-none-eabi-addr2line", "-f", "-C", "-i",
             "-e", str(elf), f"0x{(address & ~1):x}"],
            capture_output=True, text=True, check=True, timeout=15)
        return result.stdout.strip().replace("\n", " | ")
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def pwm_native_event_snapshot(rsp, elf, zero_counter):
    """Read-only native register and motor-start ISR state after DShot."""
    base = PWM4
    stat = {
        "current_pc": rsp.reg(15),
        "current_lr": rsp.reg(14),
        "pc_symbol": native_symbol_location(elf, rsp.reg(15)),
        "lr_symbol": native_symbol_location(elf, (rsp.reg(14) & ~1) - 2),
        "native_start_zero_events": rsp.mem32(zero_counter) if zero_counter else None,
        "mcpwm_tbctl": rsp.mem32(base + 0x10),
        "mcpwm_tbprd": rsp.mem32(base + 0x14),
        "mcpwm_counter": rsp.mem32(base + 0x28),
        "mcpwm_etsel": rsp.mem32(base + 0x80),
        "mcpwm_etperiod": rsp.mem32(base + 0x84),
        "mcpwm_etcnt": rsp.mem32(base + 0x88),
        "mcpwm_inten": rsp.mem32(base + 0x90),
        "mcpwm_intflag": rsp.mem32(base + 0x94),
        "mcpwm_tzsel": rsp.mem32(base + 0xA0),
        "mcpwm_tzflags": rsp.mem32(base + 0xB0),
    }
    print("G13B2E_PWM_ZERO_IRQ_NATIVE_DIAGNOSTIC " +
          json.dumps(stat, sort_keys=True), flush=True)
    return stat


def native_wait_for_bemf_calibration(rsp, wfi, observed_wfi, hardfault,
                                     armed, cal_addr, slice_ms, slices,
                                     max_visits):
    """Let original SysTick calibrate ECAP; NEVER set calibration_done."""
    for visit in range(max_visits):
        done = rsp.mem32(cal_addr)
        if done == 1:
            print(f"G13B2E_NATIVE_BEMF_ECAP_CALIBRATION_COMPLETE "
                  f"wfi_visits={visit} ORIGINAL_ELF_GUEST_WRITES_ONLY",
                  flush=True)
            return observed_wfi
        if done not in (0, 1):
            raise AssertionError(f"Invalid guest calibration_done={done}")
        del_bp(rsp, observed_wfi)
        armed.remove(observed_wfi)
        stop = rsp.command("s")  # Native instruction: original WFI
        if not stop.startswith(("S05", "T05")):
            raise RuntimeError("Native calibration WFI not stepped")
        cpu = observer(rsp)
        if cpu["cfsr"] or cpu["hfsr"] or cpu["pc"] == hardfault:
            raise AssertionError("Original firmware fault during BEMF calibration")
        if cpu["pc"] == observed_wfi:
            raise AssertionError("Guest did not execute original calibration WFI")
        add_bp(rsp, observed_wfi)
        armed.add(observed_wfi)
        observed_wfi = wait_for_native_main_wfi(
            rsp, wfi, hardfault, slice_ms, slices,
            stage=f"B2E_BEMF_CALIBRATION_{visit}")
        if visit in (0, 4, 8, 12, 16):
            print(f"G13B2E_NATIVE_CALIBRATION_PROGRESS "
                  f"visit={visit+1} done={rsp.mem32(cal_addr)} "
                  f"pc=0x{observed_wfi:08x}", flush=True)
    raise AssertionError(
        f"Native ECAP/SysTick BEMF calibration incomplete after "
        f"{max_visits} actual WFI cycles; final calibrated flag="
        f"{rsp.mem32(cal_addr)}")




def native_timeline_observe(rsp, qtest, bemf_state, *,
                            timeline, checkpoint, hardfault):
    """Read the real halted guest, native TSCTR and six hardware PWM pads."""
    state = observer(rsp)
    if (state["pc"] == hardfault or state["cfsr"] or state["hfsr"] or
            state["ipsr"] == 3):
        raise AssertionError("Original Firmware CPU fault in timeline: " +
                             json.dumps(state, sort_keys=True))
    required = ("armed", "selected_code", "calibration_done",
                "capture_ticks_per_ms")
    if any(name not in bemf_state for name in required):
        raise AssertionError("Native timeline missing original-ELF BEMF symbols")
    done = rsp.mem32(bemf_state["calibration_done"])
    ticks_per_ms = rsp.mem32(bemf_state["capture_ticks_per_ms"])
    arm = rsp.mem32(bemf_state["armed"])
    selected = rsp.mem32(bemf_state["selected_code"])
    if done != 1 or ticks_per_ms != NATIVE_ECAP_CLOCK_HZ // 1000:
        raise AssertionError(
            f"Native SysTick/ECAP calibration not qualified: "
            f"done={done} ticks_per_ms={ticks_per_ms}")
    bemf = observe_original_bemf_route(
        qtest.read, selected_code=selected, native_armed=(arm == 1))
    if not bemf.channel_ready_for_voltage_samples:
        raise AssertionError("Original native BEMF arm lost during timeline: " +
                             bemf.reason)
    frame = timeline.observe(
        qtest.read, native_ticks=qtest.read(ECAP1_TSCTR),
        checkpoint=checkpoint)
    print("G13B3D_NATIVE_PWM_TIMELINE_FRAME " +
          json.dumps(frame.to_dict(), sort_keys=True), flush=True)
    return frame






def native_sixstep_diagnostics(rsp, qtest, bemf_state):
    """All original guest SRAM and modeled MCPWM4 reads; never writes."""
    names = ("runtime_aq_updates", "runtime_pwm_updates",
             "runtime_commit_count", "runtime_phase_pending",
             "physical_shadow_dirty", "physical_runtime_image",
             "step", "sine", "prep", "sync", "oldstep",
             "pending_code", "pending_interval",
             "selected_code", "armed", "timer_armed", "scheduled",
             "serviced", "ival")
    guest = {
        k: (rsp.mem32(bemf_state[k]) if k in bemf_state else None)
        for k in names
    }
    # SDK MCPWM4 TI registers, not QEMU synthetic values. Observe
    # ACTIVE AQCTL and their SHADOW pairs, six channel outputs.
    active, shadow, compare_active, compare_shadow = [], [], [], []
    for module in range(3):
        base = PWM4 + 0x100 + module * 0x200
        for sub in (0x20, 0x28):
            active.append(qtest.read(base + sub))
            shadow.append(qtest.read(base + sub + 4))
        for sub in (0x00, 0x08):
            compare_active.append(qtest.read(base + sub))
            compare_shadow.append(qtest.read(base + sub + 4))
    # These are original ELF internal cached logical images (six
    # uint16_t), NOT values supplied/modified by the test harness.
    # If a local symbol was optimized away, mark it unobservable
    # instead of fabricating expected phase vectors.
    guest_arrays = {}
    for name in ("runtime_aq_last", "logical_aq", "logical_compare"):
        guest_arrays[name] = (
            [rsp.mem16(bemf_state[name]+2*i) for i in range(6)]
            if name in bemf_state else None)
    # Actual TI/AM13E model layout: DBFED=+0xd0, DBRED=+0xd4.
    # The previous G13B3J diagnostic reversed these 16-bit fields,
    # resulting in a false red<fed error for the original virtual board.
    dbctl, dbred, dbfed = read_native_deadband(qtest.read, PWM4)
    suppression = (
        native_deadband_source_clamp(
            guest_arrays["logical_aq"], guest_arrays["logical_compare"],
            active, red_ticks=dbred, fed_ticks=dbfed,
            fed_enabled=bool(dbctl & 2)).to_dict()
        if (guest_arrays["logical_aq"] is not None and
            guest_arrays["logical_compare"] is not None) else None)
    return {
        "guest": guest,
        "original_elf_guest_six_output_arrays": guest_arrays,
        "native_dbctl": dbctl,
        "native_dbred": dbred,
        "native_dbfed": dbfed,
        "source_pwm_deadband": suppression,
        "mcpwm4_glctl": qtest.read(PWM4 + 0xf0),
        "mcpwm4_glsts": qtest.read(PWM4 + 0xf8),
        "mcpwm4_software_force": [
            qtest.read(PWM4 + 0x130 + module*0x200)
            for module in range(3)
        ],
        "aq_active_six": active,
        "aq_shadow_six": shadow,
        "aq_active_equals_shadow": active == shadow,
        "compare_active_six": compare_active,
        "compare_shadow_six": compare_shadow,
        "compare_active_equals_shadow": compare_active == compare_shadow,
        "mcpwm4_period_active": qtest.read(PWM4 + 0x14),
        "mcpwm4_period_shadow": qtest.read(PWM4 + 0x18),
    }


def step_unchanged_native_wfi(rsp, pc, *, armed_breakpoints, wfi,
                               hardfault, slice_ms, runtime_slices, stage):
    """Debugger-only step of original WFI; never edit firmware or QEMU clock."""
    if rsp.mem16(pc) != 0xbf30:
        raise AssertionError("Original native main WFI opcode changed")
    del_bp(rsp, pc)
    armed_breakpoints.remove(pc)
    response = rsp.command("s")
    if not response.startswith(("S05", "T05")):
        raise RuntimeError("Original native WFI did not single step")
    cpu = observer(rsp)
    if cpu["pc"] == pc or cpu["pc"] == hardfault or cpu["cfsr"] or cpu["hfsr"]:
        raise AssertionError("Original native WFI failed/faulted")
    add_bp(rsp, pc)
    armed_breakpoints.add(pc)
    return wait_for_native_main_wfi(
        rsp, wfi, hardfault, slice_ms, runtime_slices, stage=stage)


def seek_later_physical_bemf_commutation(
        rsp, qtest, *, timeline, injector, bemf_state, checkpoint,
        armed_breakpoints, wfi, hardfault, slice_ms, runtime_slices, visits,
        capture_before, cap1_before, rejected_before, scheduled_before,
        serviced_before, native_pwm_before):
    """Bounded continuation after real early CAP1 rejection.

    Host may change ONLY QEMU synthetic U/V/W voltage. Never spoof native
    comparator/CAP1/IRQ/commutation/PWM/SRAM or force a clock tick.
    """
    if injector is None:
        raise ValueError("No physically integrated three-phase BEMF source")
    result = dict(
        extended_wfi_visits=0, subsequent_real_captures=0,
        subsequent_real_rejections=0,
        native_timg12_commutation_proved=False,
        reason="BOUNDED_NO_LATER_NATIVE_BEMF_EVENT")
    previous_count = capture_before
    previous_cap1 = cap1_before
    previous_rejected = rejected_before
    last_record_index = max(0, len(injector.records) - 1)
    starting_code = rsp.mem32(bemf_state["selected_code"])
    for visit in range(1, visits + 1):
        checkpoint = step_unchanged_native_wfi(
            rsp, checkpoint, armed_breakpoints=armed_breakpoints, wfi=wfi,
            hardfault=hardfault, slice_ms=slice_ms,
            runtime_slices=runtime_slices,
            stage=f"G13B3G_LATER_BEMF_{visit}")
        result["extended_wfi_visits"] = visit
        count = rsp.mem32(bemf_state["captured_events"])
        rejected = rsp.mem32(bemf_state["rejected_events"])
        scheduled = rsp.mem32(bemf_state["scheduled"])
        serviced = rsp.mem32(bemf_state["serviced"])
        armed = rsp.mem32(bemf_state["armed"])
        selected = rsp.mem32(bemf_state["selected_code"])
        if count != previous_count:
            if count != previous_count + 1:
                result["reason"] = "MULTIPLE_CAPTURES_BETWEEN_OBSERVATIONS"
                break
            cap1 = qtest.read(ECAP1_TSCTR + 8)
            proof = prove_capture_from_native_samples(
                injector.records[last_record_index:],
                cap1_before=previous_cap1,
                cap1_after=cap1, native_now=qtest.read(ECAP1_TSCTR),
                guest_count_before=previous_count,
                guest_count_after=count)
            result["subsequent_real_captures"] += 1
            result["last_later_cap1_proof"] = proof.to_dict()
            print("G13B3G_LATER_PHYSICAL_CAP1 " +
                  json.dumps(proof.to_dict(), sort_keys=True), flush=True)
            if scheduled > scheduled_before and rejected == previous_rejected:
                # The original Rel17 accepted a non-early real CAP1.
                # Only native TIMG12 ISR and distinct measured output PWM
                # can complete this gate. No additional synthetic edges.
                result["reason"] = "GUEST_ACCEPTED_BEMF_WAITING_TIMG12"
                result["accepted_at_extended_visit"] = visit
                result["original_ival_after_acceptance"] = rsp.mem32(
                    bemf_state["ival"])
                result["native_timg12_at_acceptance"] = (
                    observe_native_timg12(
                        qtest.read,
                        native_ecap_ticks=qtest.read(ECAP1_TSCTR)).to_dict())
                result["sixstep_at_acceptance"] = (
                    native_sixstep_diagnostics(rsp, qtest, bemf_state))
                print("G13B3G_NATIVE_TIMG12_AT_REAL_BEMF_ACCEPTANCE " +
                      json.dumps(result["native_timg12_at_acceptance"],
                                 sort_keys=True), flush=True)
                print("G13B3G_NATIVE_AQ_AT_REAL_BEMF_ACCEPTANCE " +
                      json.dumps(result["sixstep_at_acceptance"],
                                 sort_keys=True), flush=True)
                last_pwm_image = None
                last_serviced = serviced_before
                for wait in range(97):
                    pwm = observe_original_pwm(qtest.read, gate_active_level=1)
                    now_serviced = rsp.mem32(bemf_state["serviced"])
                    last_pwm_image = pwm.to_dict()
                    last_serviced = now_serviced
                    path_proof = qualify_cross_phase_bridge(
                        pwm.six_high_ticks, period_ticks=pwm.period_ticks,
                        gate_trip_qualified=pwm.acceptable_for_plant)
                    result["last_measured_cross_phase_power_path"] = path_proof.to_dict()
                    if (now_serviced > serviced_before and
                            path_proof.qualifies_necessary_two_terminal_drive and
                            pwm.six_high_ticks != native_pwm_before):
                        result.update(
                            native_timg12_commutation_proved=True,
                            reason="REAL_BEMF_ACCEPTED_NATIVE_TIMG12_PWM_CHANGED",
                            native_timg12_scheduled_after=scheduled,
                            native_timg12_serviced_after=now_serviced,
                            six_high_ticks_before=native_pwm_before,
                            six_high_ticks_after=pwm.six_high_ticks,
                            wait_after_acceptance=wait)
                        return result
                    if wait == 96:
                        break
                    checkpoint = step_unchanged_native_wfi(
                        rsp, checkpoint, armed_breakpoints=armed_breakpoints,
                        wfi=wfi, hardfault=hardfault, slice_ms=slice_ms,
                        runtime_slices=runtime_slices,
                        stage=f"G13B3G_TIMG12_WAIT_{wait+1}")
                result["original_timg12_serviced_after_wait"] = last_serviced
                result["native_pwm_after_wait"] = last_pwm_image
                result["sixstep_after_wait"] = (
                    native_sixstep_diagnostics(rsp, qtest, bemf_state))
                print("G13B3G_NATIVE_AQ_AFTER_TIMG12_SERVICE " +
                      json.dumps(result["sixstep_after_wait"],
                                 sort_keys=True), flush=True)
                result["native_timg12_after_wait"] = (
                    observe_native_timg12(
                        qtest.read,
                        native_ecap_ticks=qtest.read(ECAP1_TSCTR)).to_dict())
                before = result["native_timg12_at_acceptance"]
                after = result["native_timg12_after_wait"]
                if last_serviced <= serviced_before:
                    if not (before["irq_mask"] & 1):
                        result["reason"] = "NATIVE_TIMG12_IRQ_NOT_ENABLED"
                    elif before["counter_enabled"] and (
                            after["native_ecap_ticks"] -
                            before["native_ecap_ticks"]) & 0xffffffff < (
                                before["remaining_ticks"] * 2):
                        result["reason"] = "ORIGINAL_TIMER_DELAY_NOT_YET_ELAPSED"
                    else:
                        result["reason"] = "ORIGINAL_TIMG12_TIMER_NOT_SERVICED"
                elif (last_pwm_image is None or
                      last_pwm_image["six_high_ticks"] ==
                      native_pwm_before):
                    result["reason"] = "ORIGINAL_TIMG12_SERVICED_NO_PWM_CHANGE"
                    result["native_power_path_after_wait"] = (
                        result.get("last_measured_cross_phase_power_path"))
                else:
                    result["reason"] = "NATIVE_PWM_DIFFERENT_NOT_QUALIFIED"
                print("G13B3G_NATIVE_TIMG12_AFTER_BOUNDED_WAIT " +
                      json.dumps({
                          "reason":result["reason"],
                          "start":before,"end":after,
                          "native_original_serviced":last_serviced,
                          "last_pwm":last_pwm_image
                      },sort_keys=True),flush=True)
                return result
            if (rejected != previous_rejected + 1 or
                    scheduled != scheduled_before or armed != 1 or
                    selected != starting_code):
                result["reason"] = "NONQUALIFYING_ORIGINAL_BEMF_POLICY_STATE"
                return result
            result["subsequent_real_rejections"] += 1
            previous_count, previous_cap1 = count, cap1
            previous_rejected = rejected
            last_record_index = max(0, len(injector.records) - 1)
        if armed != 1 or selected != starting_code:
            result["reason"] = "ORIGINAL_GUEST_DISARMED_OR_RESELECTED"
            break
        try:
            native_timeline_observe(
                rsp, qtest, bemf_state, timeline=timeline,
                checkpoint=f"extended_native_main_wfi_{visit}",
                hardfault=hardfault)
            analog = injector.inject(
                timeline, qtest.read, qtest.write,
                selected_code=selected, native_armed=True)
        except ValueError as exc:
            result["reason"] = "NATIVE_PWM_OR_MOTOR_ANALOG_UNQUALIFIED"
            result["details"] = str(exc)
            break
        if visit % 16 == 0:
            print("G13B3G_EXTENDED_NATIVE_FEEDBACK_PROGRESS " +
                  json.dumps({
                      "visit":visit,
                      "motor_elapsed_ns":analog.motor_elapsed_ns,
                      "guest_captures":count, "guest_rejections":rejected,
                      "timg12_scheduled":scheduled,
                      "timg12_serviced":serviced,
                      "rpm":round(timeline.frames[-1].mechanical_rpm,3),
                      "six_high_ticks":timeline.frames[-1].six_high_ticks,
                      "analog_codes":[v & 0xfff for v in analog.sample_words]
                  },sort_keys=True), flush=True)
    result["motor_elapsed_ns"] = timeline.frames[-1].elapsed_ns
    result["integrated_plant_ns"] = timeline.frames[-1].total_integrated_ns
    return result




def observe_original_no_bemf_timeout(
        rsp, qtest, *, bemf_state, armed_breakpoints, wfi, hardfault,
        slice_ms, runtime_slices, max_visits):
    """No host analog writes. Wait for native SysTick to disarm ECAP1."""
    fields = ("armed", "crossing_epoch", "crossing_epoch_valid",
              "capture_timeout_ticks", "capture_ticks_per_ms",
              "calibration_done", "captured_events", "rejected_events",
              "cancelled", "ertm")
    if any(k not in bemf_state for k in fields):
        raise AssertionError("Cannot audit original no-BEMF symbols")
    guest = lambda name: rsp.mem32(bemf_state[name])
    if guest("calibration_done") != 1:
        raise AssertionError("Original 200MHz ECAP SysTick uncalibrated")
    start = {name:guest(name) for name in fields}
    if (start["armed"] != 1 or
            start["crossing_epoch_valid"] != 1 or
            start["capture_ticks_per_ms"] != 200000 or
            not 0 < start["capture_timeout_ticks"] < 0x80000000):
        raise AssertionError("Original native BEMF capture not ready")
    def voltage_words():
        return tuple(qtest.read(SIM_BEMF_INPUT+4*i) for i in range(3))
    if any(v & 0x10000 for v in voltage_words()):
        raise AssertionError("QEMU already has valid BEMF input")
    for pc in sorted(armed_breakpoints-{hardfault}):
        del_bp(rsp, pc)
        armed_breakpoints.remove(pc)
    for pc in wfi:
        if pc not in armed_breakpoints:
            add_bp(rsp, pc)
            armed_breakpoints.add(pc)
    checkpoint = wait_for_native_main_wfi(
        rsp, wfi, hardfault, slice_ms, runtime_slices,
        stage="G13B3I_NO_VALID_BEMF_FIRST_WFI")
    for visit in range(1, max_visits+1):
        if observer(rsp)["cfsr"] or observer(rsp)["hfsr"]:
            raise AssertionError("Original CPU fault during no-BEMF supervision")
        if guest("captured_events") != start["captured_events"] or (
                guest("rejected_events") != start["rejected_events"]):
            raise AssertionError("Native capture without a valid BEMF sample")
        if guest("armed") == 0:
            result = prove_native_no_feedback_timeout(
                epoch=start["crossing_epoch"],
                timeout_ticks=start["capture_timeout_ticks"],
                cap_end_ticks=qtest.read(ECAP1_TSCTR),
                armed_before=start["armed"],
                armed_after=guest("armed"),
                epoch_valid_before=start["crossing_epoch_valid"],
                epoch_valid_after=guest("crossing_epoch_valid"),
                ticks_per_ms=guest("capture_ticks_per_ms"),
                captured_before=start["captured_events"],
                captured_after=guest("captured_events"),
                rejected_before=start["rejected_events"],
                rejected_after=guest("rejected_events"),
                cancelled_before=start["cancelled"],
                cancelled_after=guest("cancelled"),
                ertm_after=guest("ertm"),
                simulator_bemf_words=voltage_words(),
                physical_tz_flags=qtest.read(PWM4+0xb0))
            report = result.to_dict()
            report["original_wfi_visits"]=visit
            report["simulator_feedback_injected"]=False
            print("PASS_G13B3I_ORIGINAL_ECAP_SYSTICK_NO_BEMF_TIMEOUT " +
                  json.dumps(report,sort_keys=True),flush=True)
            return report
        if visit % 64 == 0:
            print("G13B3I_ORIGINAL_NO_BEMF_WAIT " +
                  json.dumps({"visit":visit,
                              "original_armed":guest("armed"),
                              "elapsed_ecap_ticks":(
                                  qtest.read(ECAP1_TSCTR)-
                                  start["crossing_epoch"]) & 0xffffffff,
                              "required_timeout_ticks":
                                  start["capture_timeout_ticks"]},
                             sort_keys=True),flush=True)
        checkpoint = step_unchanged_native_wfi(
            rsp, checkpoint, armed_breakpoints=armed_breakpoints,
            wfi=wfi, hardfault=hardfault,
            slice_ms=slice_ms, runtime_slices=runtime_slices,
            stage=f"G13B3I_NO_BEMF_NATIVE_WFI_{visit}")
    raise AssertionError(
        "No original SysTick/ECAP capture timeout within bounded native "
        f"WFI visits={max_visits}; original_armed={guest('armed')}")





def original_duty_config_audit(rsp, bemf_state):
    """Read-only ABI source-audited ESCape32 src/common.h Cfg structure.

    Pinned Cfg: id[0..1], revision[2], revpatch[3], name[4..18],
    _null[19], arm[20], ... freq_max[28], duty_min[29],
    duty_max[30], duty_spup[31], duty_ramp[32], duty_rate[33].
    Reads two 32-bit naturally aligned original Guest cfg words only.
    """
    cfg = bemf_state.get("cfg")
    if cfg is None:
        raise AssertionError("Original ELF cfg symbol missing")
    x = rsp.mem32(cfg+28)
    y = rsp.mem32(cfg+32)
    rates = {
        "freq_max_khz": x&0xff,
        "duty_min_pct": (x>>8)&0xff,
        "duty_max_pct": (x>>16)&0xff,
        "duty_spup_pct": (x>>24)&0xff,
        "duty_ramp_kerpm": y&0xff,
        "duty_rate_tenth_pct_per_ms": (y>>8)&0xff,
        "duty_drag_pct": (y>>16)&0xff,
        "duty_lock_mode": (y>>24)&0xff,
    }
    if not (16<=rates["freq_max_khz"]<=96 and
            1<=rates["duty_min_pct"]<=100 and
            1<=rates["duty_max_pct"]<=100 and
            1<=rates["duty_spup_pct"]<=100 and
            1<=rates["duty_rate_tenth_pct_per_ms"]<=100):
        raise AssertionError("Original native Cfg ABI not qualified: " +
                             repr(rates))
    return rates


def native_pwm_duty_progress(rsp, bemf_state, qtest):
    """Guest tick/throt/ertm and original active/shadow compares, no writes."""
    report = original_duty_config_audit(rsp, bemf_state)
    for key in ("tick","throt","erpm","ertm","runtime_pwm_updates",
                "runtime_aq_updates","runtime_commit_count",
                "armed","cancelled","crossing_epoch_valid"):
        report[key] = (rsp.mem32(bemf_state[key])
                       if key in bemf_state else None)
    if "logical_compare" in bemf_state:
        report["original_logical_compare"] = [
            rsp.mem16(bemf_state["logical_compare"]+2*i)
            for i in range(6)]
    report["ecap1_tsctr"] = qtest.read(ECAP1_TSCTR)
    # ECCTL1/ECCTL2 are packed at actual ECAP1 +0x28, bits [31:16]
    # carry ECCTL2. +0x1c is CTRPHS, NOT ECCTL2.
    report["ecap1_ecctl2"] = (qtest.read(ECAP1_TSCTR+0x28)>>16)&0xffff
    report["mcpwm_active_compare"] = [
        qtest.read(PWM4+0x100+0x200*i+0x4*j)
        for i in range(3) for j in (0,2)]
    report["mcpwm_shadow_compare"] = [
        qtest.read(PWM4+0x100+0x200*i+0x4*j)
        for i in range(3) for j in (1,3)]
    return report


def evidence_power(proof):
    """Do not claim effective power from only one PWM read or mock speed."""
    return proof if proof is not None else {
        "qualified": False,
        "reason": "NO_THREE_CONSECUTIVE_CROSS_PHASE_POWERED_WFI"}

def probe_native_sustained_power_feedback(
        rsp, qtest, *, bemf_state, armed_breakpoints, wfi, hardfault,
        slice_ms, runtime_slices, max_visits, required_sectors,
        require_sim_only_cfg=False, initial_electrical_degrees=0.0,
        required_integrated_ns=0, trace=None, live=None):
    """Full native WFI-to-WFI physical bridge -> plant -> BEMF feedback loop.

    No native program counter, firmware SRAM, PWM, TIMG12, CAP1, or IRQ
    writes. Only physical voltage stimulus (NON-SILICON QTest port).
    Only original guest CAP1 + TIMG12 service + powered six-vector can
    result in a completed sector. SIM_ONLY assumptions stay explicit.
    """
    needed = ("armed", "pending_code", "selected_code", "step",
              "captured_events", "rejected_events", "scheduled", "serviced")
    missing = [x for x in needed if x not in bemf_state]
    if missing:
        raise AssertionError("Original ELF missing native loop symbols: " +
                             ",".join(missing))
    motor = NativePowerCoupledBLDC(MotorParameters(
        vbus_v=24.0, phase_resistance_ohm=.3,
        phase_inductance_h=.002, bemf_constant_v_per_rad_s=.02,
        torque_constant_nm_per_a=.02, inertia_kg_m2=1e-6,
        viscous_friction_nm_per_rad_s=.0001, load_torque_nm=0,
        pole_pairs=7),
        initial_electrical_rad=math.radians(initial_electrical_degrees))
    print("G13B3L_EXPLICIT_SIM_ONLY_ROTOR_POSE " +
          json.dumps({
              "initial_electrical_degrees": initial_electrical_degrees,
              "initial_motor_rpm": motor.sample().mechanical_rpm,
              "initial_three_phase_bemf_v": motor.sample().bemf_phase_v,
              "applied_external_torque": False,
              "host_forced_capture_irq": False
          },sort_keys=True), flush=True)
    timeline = NativePwmTimeline(motor)
    frontend = AnalogFrontend(reference_v=3.3, zero_bemf_bias_v=1.65,
                              input_gain_v_per_bemf_v=.02)
    audit = NativeClosedLoopAudit(required_sectors=required_sectors)
    rotor_motion = NativeRotorMotionAudit()
    for pc in sorted(armed_breakpoints - {hardfault}):
        del_bp(rsp, pc)
        armed_breakpoints.remove(pc)
    for pc in wfi:
        if pc not in armed_breakpoints:
            add_bp(rsp, pc)
            armed_breakpoints.add(pc)

    # The original motor is stationary: no fabricated initial speed.
    initial = timeline.observe(
        qtest.read, native_ticks=qtest.read(ECAP1_TSCTR),
        checkpoint="native_gate_return_before_sustained_motor")
    if trace is not None:
        trace.set_gate_origin(initial)  # reuse existing ECAP observation
        if live is not None:
            live.hub.begin(trace.meta)
    if motor.sample().mechanical_rpm != 0:
        raise AssertionError("Synthetic motor did not start at zero RPM")
    last_qualified_path = False
    consecutive_powered_wfi = 0
    effective_power_proof = None
    total_written = 0
    record_last = {}
    result = {}
    first_qualified_wfi = None
    duty_first = native_pwm_duty_progress(rsp, bemf_state, qtest)
    print("G13B3L_GUEST_DUTY_AT_GATE " +
          json.dumps(duty_first, sort_keys=True), flush=True)
    if require_sim_only_cfg:
        # Exact pinned ESCape32 Cfg ABI and isolated SIM_ONLY Rel17 profile.
        # Application-only QEMU must not silently use zeroed .cfg NOLOAD RAM.
        # No Host/firmware variable writes are permitted to make this pass.
        expected = {
            "duty_rate_tenth_pct_per_ms": 100,
            "duty_max_pct": 100,
            "duty_spup_pct": 15,
            "freq_max_khz": 48,
        }
        wrong = {k: {"expected": v, "native": duty_first[k]}
                 for k,v in expected.items() if duty_first[k] != v}
        if wrong:
            raise AssertionError(
                "G13B3L_SOURCE_DEFINED_CFG_NOT_ACTUALLY_INITIALIZED_IN_GUEST: "
                + json.dumps(wrong, sort_keys=True))
        print("PASS_G13B3L_SOURCE_CFG_ACTUAL_GUEST_VALUES " +
              json.dumps(expected, sort_keys=True), flush=True)
    for visit in range(1, max_visits + 1):
        checkpoint = wait_for_native_main_wfi(
            rsp, wfi, hardfault, slice_ms, runtime_slices,
            stage=f"G13B3L_NATIVE_MOTOR_LOOP_{visit}")
        cpu = observer(rsp)
        if cpu["pc"] == hardfault or cpu["cfsr"] or cpu["hfsr"]:
            raise AssertionError("Original ELF fault in sustained motor")
        try:
            frame = timeline.observe(
                qtest.read, native_ticks=qtest.read(ECAP1_TSCTR),
                checkpoint=f"native_sustained_wfi_{visit}")
            # Same stopped Guest, same single observed physical output
            # image used for BOTH motor integration and strict CAP1/PWM
            # auditing. Do not reread an unchanged checkpoint's MMIO.
            real_pwm = timeline.last_observation
            if (real_pwm is None or
                    real_pwm.six_high_ticks != frame.six_high_ticks or
                    real_pwm.period_ticks != frame.pwm_period_ticks):
                raise AssertionError("WFI PWM observer/frame coherence lost")
            path = qualify_cross_phase_bridge(
                real_pwm.six_high_ticks,
                period_ticks=real_pwm.period_ticks,
                gate_trip_qualified=real_pwm.acceptable_for_plant)
            last_qualified_path = (
                path.qualifies_necessary_two_terminal_drive)
            consecutive_powered_wfi = (consecutive_powered_wfi + 1
                if last_qualified_path else 0)
            sample = motor.sample(gate_enabled=last_qualified_path)
            if (effective_power_proof is None and
                    consecutive_powered_wfi >= 3 and
                    motor.energized_intervals >= 2 and
                    motor.mechanically_productive_intervals >= 2 and
                    motor.net_dc_input_energy_j > 0.0 and
                    motor.net_electromagnetic_work_j > 0.0 and
                    abs(sample.mechanical_rpm) > 0):
                effective_power_proof = {
                    "native_ecap_ticks": frame.native_ecap_ticks,
                    "original_wfi_visit": visit,
                    "qualified_consecutive_wfi": consecutive_powered_wfi,
                    "native_six_high_ticks": real_pwm.six_high_ticks,
                    "physical_power_pairs": path.different_phase_pairs,
                    "motor_energized_intervals": motor.energized_intervals,
                    "motor_rpm_after_measured_power": sample.mechanical_rpm,
                    "simulated_dc_input_power_w":
                        motor.last_dc_input_power_w,
                    "simulated_electromagnetic_shaft_power_w":
                        motor.last_electromagnetic_power_w,
                    "simulated_net_dc_energy_j":
                        motor.net_dc_input_energy_j,
                    "simulated_net_electromagnetic_work_j":
                        motor.net_electromagnetic_work_j,
                    "gate_connected": real_pwm.gate_and_pads,
                    "original_ost2_clear": not real_pwm.physical_ost2,
                    "original_ost3_clear": not real_pwm.physical_ost3}
                print("PASS_G13B3L_NATIVE_MEASURED_TWO_TERMINAL_POWER_"
                      "DRIVES_SIM_ONLY_MOTOR " +
                      json.dumps(effective_power_proof, sort_keys=True),
                      flush=True)
            analog = frontend.words(sample)
        except (ValueError, FloatingPointError) as exc:
            at_failure = native_pwm_duty_progress(rsp, bemf_state, qtest)
            reason = ("NATIVE_ECAP_TIMEBASE_STALLED" if
                      "delta_ticks=0" in str(exc) else
                      "UNQUALIFIED_PHYSICAL_MOTOR_OR_ANALOG")
            result = dict(qualified=False, reason=reason,
                          details=str(exc), original_guest_wfi_visits=visit,
                          guest_duty_at_gate=duty_first,
                          original_duty_and_timer_at_failure=at_failure)
            print("G13B3L_REAL_DUTY_AND_ECAP_BLOCKER " +
                  json.dumps(result, sort_keys=True), flush=True)
            break
        # Real analog lines remain present even when guest ECAP is
        # unarmed. The guest alone selects/arms comparator and timer.
        # Never gate or spoof IRQ by writing an enable/flag bit.
        for phase, word in enumerate(analog):
            qtest.write(SIM_BEMF_INPUT + 4 * phase, word)
        for phase, word in enumerate(analog):
            if qtest.read(SIM_BEMF_INPUT + 4 * phase) != word:
                raise AssertionError("Native analog input MMIO corrupted")
        total_written += 1
        guest = {
            name: rsp.mem32(bemf_state[name])
            for name in needed
        }
        cap1 = qtest.read(ECAP1_TSCTR + 8)
        try:
            audit.ingest(
                ecap_ticks=frame.native_ecap_ticks,
                cap1_ticks=cap1,
                captured=guest["captured_events"],
                rejected=guest["rejected_events"],
                scheduled=guest["scheduled"],
                serviced=guest["serviced"],
                step=guest["step"],
                selected_code=guest["selected_code"],
                pwm_high=real_pwm.six_high_ticks,
                pwm_period=real_pwm.period_ticks,
                gate_trip_qualified=real_pwm.acceptable_for_plant,
                rpm=sample.mechanical_rpm,
                armed=(guest["armed"] == 1),
                pending_code=guest["pending_code"])
        except AssertionError as exc:
            # Fail closed, but retain the SOURCE-owned old/now Guest state
            # and independent SIM_ONLY motion trend. Never hide a bad CAP1,
            # missed TIMG12, reset, reversed rotor, or Trip.
            rotor_motion.observe(
                wfi_visit=visit, completed_sectors=len(audit.sectors),
                integrated_ns=frame.total_integrated_ns,
                rpm=sample.mechanical_rpm,
                phase_currents_a=sample.phase_currents_a,
                dc_power_w=motor.last_dc_input_power_w)
            print("G13B3M_FAIL_CLOSED_NATIVE_LOOP_DIAGNOSTIC " +
                  json.dumps({
                      "reason": str(exc), "native_guest_wfi_visit": visit,
                      "guest_event_counters": guest,
                      "previous_native_audit_state": audit.last,
                      "pending_original_cap1_timg12": audit.pending,
                      "completed_native_sectors": len(audit.sectors),
                      "sim_only_motion": rotor_motion.result(),
                      "host_guest_writes": False,
                  }, sort_keys=True), flush=True)
            raise
        rotor_motion.observe(
            wfi_visit=visit, completed_sectors=len(audit.sectors),
            integrated_ns=frame.total_integrated_ns,
            rpm=sample.mechanical_rpm,
            phase_currents_a=sample.phase_currents_a,
            dc_power_w=motor.last_dc_input_power_w)
        if trace is not None:
            # Both offline/live consume ONLY snapshots already obtained here.
            # The live publisher appends in-memory (no browser I/O on Guest).
            packet = trace.observe(visit=visit, frame=frame, pwm=real_pwm,
                                   plant=sample, guest=guest, analog=analog,
                                   cap1_ticks=cap1, sectors=audit.sectors)
            if live is not None:
                live.hub.publish(packet["sample"], packet["events"])
        if visit <= 3 or visit % 16 == 0:
            print("G13B3L_NATIVE_GUEST_DUTY_PROGRESS " +
                  json.dumps({
                      "visit": visit,
                      "state": native_pwm_duty_progress(
                          rsp, bemf_state, qtest)
                  }, sort_keys=True), flush=True)
        if (visit <= 3 or visit % 32 == 0 or
                audit.qualified or
                len(audit.sectors) != record_last.get("sectors", 0)):
            report = {
                "visit": visit,
                "native_guest_step": guest["step"],
                "native_guest_armed": guest["armed"],
                "original_captured": guest["captured_events"],
                "original_rejected": guest["rejected_events"],
                "original_scheduled": guest["scheduled"],
                "original_serviced": guest["serviced"],
                "measured_six_high_ticks": real_pwm.six_high_ticks,
                "physical_source_return_pairs": path.different_phase_pairs,
                "motor_rpm": sample.mechanical_rpm,
                "motor_energized_intervals": motor.energized_intervals,
                "motor_coast_intervals": motor.coasting_intervals,
                "simulated_dc_input_power_w": motor.last_dc_input_power_w,
                "simulated_electromagnetic_shaft_power_w":
                    motor.last_electromagnetic_power_w,
                "simulated_net_dc_energy_j": motor.net_dc_input_energy_j,
                "simulated_net_electromagnetic_work_j":
                    motor.net_electromagnetic_work_j,
                "real_completed_sectors": len(audit.sectors),
                "analog_codes": [v & 0xfff for v in analog]
            }
            print("G13B3L_NATIVE_POWERED_MOTOR_LOOP " +
                  json.dumps(report, sort_keys=True), flush=True)
            record_last["sectors"] = len(audit.sectors)
        if audit.qualified and first_qualified_wfi is None:
            first_qualified_wfi = visit
        # Only the G13B3M opt-in endpoint continues beyond sector 12.
        # Keep the ORIGINAL native WFI/PWM/ECAP/Trip path genuinely powered.
        if (first_qualified_wfi is not None and required_integrated_ns
                and not last_qualified_path):
            raise AssertionError(
                "Original Guest powered bridge lost during native endurance tail")
        if (first_qualified_wfi is not None and required_integrated_ns
                and timeline.frames[-1].total_integrated_ns < required_integrated_ns
                and visit % 32 == 0):
            print("G13B3M_NATIVE_ENDURANCE_ECAP_TIME_PENDING " +
                  json.dumps({
                      "visit": visit,
                      "accepted_powered_sectors": len(audit.sectors),
                      "native_integrated_ns": timeline.frames[-1].total_integrated_ns,
                      "required_integrated_ns": required_integrated_ns,
                      "host_guest_writes": False,
                  }, sort_keys=True), flush=True)
        if (audit.qualified and
                timeline.frames[-1].total_integrated_ns >= required_integrated_ns
                and audit.pending is None):
            if effective_power_proof is None:
                raise AssertionError(
                    "Six guest sectors cannot pass without three measured "
                    "consecutive physically powered WFI and model RPM")
            result = audit.result()
            result.update(
                original_guest_wfi_visits=visit,
                required_native_integrated_ns=required_integrated_ns,
                first_qualified_wfi_visit=first_qualified_wfi,
                native_powered_endurance_tail_wfi_visits=visit-first_qualified_wfi,
                last_measured_power_path=last_qualified_path,
                sim_only_rotor_motion=rotor_motion.result(),
                plant_max_rpm=motor.max_measured_rpm,
                plant_integrated_ns=timeline.frames[-1].total_integrated_ns,
                simulator_analog_frames=total_written,
                motor_started_only_after_cross_phase=(
                    motor.ever_powered and
                    motor.energized_intervals > 0),
                native_effective_power=evidence_power(effective_power_proof))
            print("PASS_G13B3L_ORIGINAL_NATIVE_SIX_FEEDBACK_POWERED_"
                  "COMMUTATIONS_SIM_ONLY " +
                  json.dumps(result, sort_keys=True), flush=True)
            if trace is not None:
                trace.finish(result)  # never asserts extended gate PASS
            return result
        if visit == max_visits:
            break
        checkpoint = step_unchanged_native_wfi(
            rsp, checkpoint, armed_breakpoints=armed_breakpoints,
            wfi=wfi, hardfault=hardfault,
            slice_ms=slice_ms, runtime_slices=runtime_slices,
            stage=f"G13B3L_NEXT_ORIGINAL_WFI_{visit}")
    if not result:
        result = audit.result()
        if required_integrated_ns and (
                timeline.frames[-1].total_integrated_ns < required_integrated_ns
                or audit.pending is not None or not last_qualified_path):
            result["qualified"] = False
            result["reason"] = "STRICT_NATIVE_ECAP_ENDURANCE_OR_POWER_INCOMPLETE"
        result.update(
            sim_only_rotor_motion=rotor_motion.result(),
            required_native_integrated_ns=required_integrated_ns,
            first_qualified_wfi_visit=first_qualified_wfi,
            original_guest_wfi_visits=max_visits,
            plant_max_rpm=motor.max_measured_rpm,
            plant_integrated_ns=timeline.frames[-1].total_integrated_ns,
            simulator_analog_frames=total_written,
            motor_started_only_after_cross_phase=(
                motor.ever_powered and motor.energized_intervals > 0),
            native_effective_power=evidence_power(effective_power_proof),
            last_measured_power_path=last_qualified_path)
    print("G13B3L_OPEN_SUSTAINED_NATIVE_CLOSED_LOOP " +
          json.dumps(result, sort_keys=True), flush=True)
    if trace is not None:
        trace.finish(result)
    return result


def collect_native_pwm_timeline(
    rsp, qtest, *, hardfault, armed_breakpoints, wfi, bemf_state,
    slice_ms, runtime_slices, visits, motor, frontend=None,
    require_capture=False, probe_commutation=False,
    require_early_rejection=False, extended_feedback_visits=0):
    """GDB WFI rendezvous samples genuine guest time, never clock_step.

    Guest continues to execute between *original* WFI instructions.
    ECAP1's actual 200MHz TSCTR timestamps each sample. QTest performs
    readl only throughout this function. Nothing is injected into CMPSS.
    """
    timeline = NativePwmTimeline(motor)
    injector = NativeBemfInjector(frontend) if frontend is not None else None
    if require_capture and injector is None:
        raise ValueError("Native CAP1 proof requires real analog stimulus")
    initial_capture_count = (
        rsp.mem32(bemf_state["captured_events"]) if require_capture else 0)
    initial_cap1 = qtest.read(ECAP1_TSCTR + 8) if require_capture else 0
    capture_proof = None
    commutation_proof = None
    if (probe_commutation or require_early_rejection) and not require_capture:
        raise ValueError("Native commutation/policy audit requires real CAP1")
    scheduled_before = (
        rsp.mem32(bemf_state["scheduled"]) if probe_commutation else None)
    serviced_before = (
        rsp.mem32(bemf_state["serviced"]) if probe_commutation else None)
    if require_early_rejection:
        required = ("ival", "crossing_epoch", "crossing_epoch_valid",
                    "rejected_events", "scheduled", "armed", "selected_code")
        if any(name not in bemf_state for name in required):
            raise AssertionError(
                "Original ELF has ambiguous/missing Rel17 policy symbols")
        policy_before = {
            name: rsp.mem32(bemf_state[name])
            for name in ("ival", "crossing_epoch", "crossing_epoch_valid",
                         "rejected_events", "scheduled", "selected_code")
        }
    else:
        policy_before = None
    early_rejection = None

    def feed_if_requested():
        if injector is None:
            return
        selected = rsp.mem32(bemf_state["selected_code"])
        native_armed = rsp.mem32(bemf_state["armed"]) == 1
        record = injector.inject(
            timeline, qtest.read, qtest.write,
            selected_code=selected, native_armed=native_armed)
        print("G13B3E_NATIVE_THREE_PHASE_PLANT_BEMF_INPUT " +
              json.dumps(record.to_dict(), sort_keys=True), flush=True)

    # Remove legacy gate/start/IRQ observation breakpoints before
    # sampling: those would arrest the CPU at unrelated native events.
    # Keep the original HardFault breakpoint as an explicit safety trip.
    for pc in sorted(armed_breakpoints - {hardfault}):
        del_bp(rsp, pc)
        armed_breakpoints.remove(pc)
    for pc in wfi:
        if pc not in armed_breakpoints:
            add_bp(rsp, pc)
            armed_breakpoints.add(pc)
    native_timeline_observe(
        rsp, qtest, bemf_state, timeline=timeline,
        checkpoint="native_gate_return", hardfault=hardfault)
    feed_if_requested()
    for visit in range(visits):
        checkpoint = wait_for_native_main_wfi(
            rsp, wfi, hardfault, slice_ms, runtime_slices,
            stage=f"G13B3D_TIMELINE_{visit + 1}")
        if require_capture:
            # The native IRQ can legitimately consume/disarm BEMF before
            # this WFI. Observe its own counter BEFORE requiring rearm.
            count = rsp.mem32(bemf_state["captured_events"])
            cap1 = qtest.read(ECAP1_TSCTR + 8)
            if count > initial_capture_count:
                capture_proof = prove_capture_from_native_samples(
                    injector.records, cap1_before=initial_cap1,
                    cap1_after=cap1, native_now=qtest.read(ECAP1_TSCTR),
                    guest_count_before=initial_capture_count,
                    guest_count_after=count)
                print("G13B3F_NATIVE_CAPTURE_ECAP_IRQ_CAUSAL " +
                      json.dumps(capture_proof.to_dict(), sort_keys=True),
                      flush=True)
                if require_early_rejection:
                    early_rejection = prove_original_early_rejection(
                        cap1_ticks=cap1,
                        epoch_ticks=policy_before["crossing_epoch"],
                        ticks_per_ms=rsp.mem32(
                            bemf_state["capture_ticks_per_ms"]),
                        original_ival_us=policy_before["ival"],
                        rejected_before=policy_before["rejected_events"],
                        rejected_after=rsp.mem32(
                            bemf_state["rejected_events"]),
                        scheduled_before=policy_before["scheduled"],
                        scheduled_after=rsp.mem32(
                            bemf_state["scheduled"]),
                        armed_after=rsp.mem32(bemf_state["armed"]),
                        selected_after=rsp.mem32(
                            bemf_state["selected_code"]),
                        selected_before=policy_before["selected_code"],
                        epoch_valid_before=policy_before[
                            "crossing_epoch_valid"])
                    print("PASS_G13B3G_ORIGINAL_REL17_EARLY_BEMF_REJECT "
                          "REAL_CAP1_ISR_NO_TIMG12_SCHEDULE_ARM_PRESERVED " +
                          json.dumps(early_rejection.to_dict(),
                                     sort_keys=True), flush=True)
                if probe_commutation:
                    # Guest-owned schedule/dispatch counters are never
                    # written by the test. A captured *early* edge may
                    # correctly be rejected by unchanged Rel17 policy.
                    scheduled_at_capture = rsp.mem32(
                        bemf_state["scheduled"])
                    rejected_at_capture = rsp.mem32(
                        bemf_state["rejected_events"])
                    commutation_proof = {
                        "scheduled_before_capture": scheduled_before,
                        "scheduled_after_capture": scheduled_at_capture,
                        "serviced_before_capture": serviced_before,
                        "rejected_edges_original": rejected_at_capture,
                        "native_capture_count": count,
                        "native_timg12_commutation_proved": False,
                        "reason": "REJECTED_OR_NOT_SCHEDULED"
                    }
                    if (scheduled_at_capture == scheduled_before and
                            extended_feedback_visits > 0 and
                            rejected_at_capture > 0 and
                            rsp.mem32(bemf_state["armed"]) == 1):
                        continuation = seek_later_physical_bemf_commutation(
                            rsp, qtest, timeline=timeline, injector=injector,
                            bemf_state=bemf_state, checkpoint=checkpoint,
                            armed_breakpoints=armed_breakpoints, wfi=wfi,
                            hardfault=hardfault, slice_ms=slice_ms,
                            runtime_slices=runtime_slices,
                            visits=extended_feedback_visits,
                            capture_before=count, cap1_before=cap1,
                            rejected_before=rejected_at_capture,
                            scheduled_before=scheduled_at_capture,
                            serviced_before=serviced_before,
                            native_pwm_before=timeline.frames[-1].six_high_ticks)
                        commutation_proof.update(continuation)
                    if scheduled_at_capture > scheduled_before:
                        # Only a real original TIMG12 ISR may increment
                        # serviced. Continue original CPU after native WFI,
                        # but DO NOT feed speculative further BEMF or touch
                        # any native register/firmware state.
                        original_pwm = timeline.frames[-1].six_high_ticks
                        for extra in range(96):
                            if rsp.mem16(checkpoint) != 0xbf30:
                                raise AssertionError("Native WFI opcode changed")
                            del_bp(rsp, checkpoint)
                            armed_breakpoints.remove(checkpoint)
                            stp = rsp.command("s")
                            if not stp.startswith(("S05", "T05")):
                                raise RuntimeError("Native WFI step failed")
                            cpu = observer(rsp)
                            if cpu["pc"] == hardfault or cpu["cfsr"] or cpu["hfsr"]:
                                raise AssertionError("Original firmware fault")
                            add_bp(rsp, checkpoint)
                            armed_breakpoints.add(checkpoint)
                            checkpoint = wait_for_native_main_wfi(
                                rsp, wfi, hardfault, slice_ms, runtime_slices,
                                stage=f"G13B3G_ORIGINAL_COMMUTATION_{extra+1}")
                            now_image = observe_original_pwm(
                                qtest.read, gate_active_level=1)
                            serviced = rsp.mem32(bemf_state["serviced"])
                            if (serviced > serviced_before and
                                    now_image.acceptable_for_plant and
                                    now_image.six_high_ticks != original_pwm):
                                commutation_proof.update(
                                    native_timg12_commutation_proved=True,
                                    reason="ORIGINAL_TIMG12_ISR_PWM_CHANGED",
                                    serviced_after=serviced,
                                    six_high_ticks_before=original_pwm,
                                    six_high_ticks_after=now_image.six_high_ticks,
                                    post_capture_wfi_visits=extra + 1)
                                break
                        if not commutation_proof["native_timg12_commutation_proved"]:
                            commutation_proof["reason"] = (
                                "SCHEDULED_BUT_NO_QUALIFIED_NATIVE_PWM_CHANGE")
                    print("G13B3G_ORIGINAL_CAPTURE_TO_COMMUTATION " +
                          json.dumps(commutation_proof, sort_keys=True),
                          flush=True)
                break
        native_timeline_observe(
            rsp, qtest, bemf_state, timeline=timeline,
            checkpoint=f"original_main_wfi_{visit + 1}",
            hardfault=hardfault)
        feed_if_requested()
        if visit + 1 != visits:
            # Execute the actual WFI opcode once so the next observation
            # is a new genuine entry, not the same halted breakpoint.
            if rsp.mem16(checkpoint) != 0xbf30:
                raise AssertionError("Observed main WFI opcode changed")
            del_bp(rsp, checkpoint)
            armed_breakpoints.remove(checkpoint)
            stopped = rsp.command("s")
            if not stopped.startswith(("S05", "T05")):
                raise RuntimeError("Original native WFI step did not stop")
            st = observer(rsp)
            if st["pc"] == hardfault or st["cfsr"] or st["hfsr"]:
                raise AssertionError("Original CPU fault after WFI")
            if st["pc"] == checkpoint:
                raise AssertionError("Original WFI failed to advance")
            add_bp(rsp, checkpoint)
            armed_breakpoints.add(checkpoint)
    if require_capture and capture_proof is None:
        raise AssertionError(
            "No genuine original ECAP1_IRQHandler captured_events and "
            "CAP1 from modeled three-phase BEMF within bounded WFI visits")
    result = timeline.require_progress(
        min_frames=(3 if require_capture else visits + 1),
        min_integrated_intervals=2)
    if injector is not None:
        result["bemf_injection"] = injector.require_samples(
            min_samples=(3 if require_capture else visits + 1))
    if capture_proof is not None:
        result["native_bemf_capture"] = capture_proof.to_dict()
    if commutation_proof is not None:
        result["original_commutation"] = commutation_proof
    if early_rejection is not None:
        result["original_early_rejection"] = early_rejection.to_dict()
    return result

def run(args):
    app_vector_from_elf(args.elf)
    wfi = native_wfi_locations(args.elf, args.objdump)
    throt = symbol_address(args.elf, "throt")
    try:
        native_start_zero_counter = symbol_address(
            args.elf, "start_zero_events")
    except RuntimeError:
        native_start_zero_counter = None  # do not fabricate guest values
    symbols = {
        name: elf_function_address(args.elf, name)[0]
        for name in ("am13e_app_io_dshot_packet", "am13e_motor_output_start",
                     "am13e_power_stage_enable", FAULT_FN,
                     "MCPWM4_IRQHandler",
                     "am13e_app_motor_nfault_trip_ready",
                     "am13e_app_motor_bemf_reference_start_ready")
    }
    try:
        symbols["bemf_fault"] = elf_function_address(args.elf, "bemf_fault")[0]
    except ValueError:
        symbols["bemf_fault"] = None
    bemf_state = {}
    for name in ("cfg","tick","throt","erpm","valid_frame_feeds",
                  "calibration_done", "calibration_ticks",
                 "capture_ticks_per_ms", "capture_timeout_ticks",
                 "pending_code", "pending_interval",
                 "reference_ready", "selected_code", "armed",
                 "captured_events", "rejected_events",
                 "scheduled", "serviced", "ival",
                 "crossing_epoch", "crossing_epoch_valid",
                 "cancelled", "ertm", "runtime_aq_updates",
                 "runtime_pwm_updates", "runtime_commit_count",
                 "runtime_phase_pending", "physical_shadow_dirty",
                 "physical_runtime_image", "step", "sine", "prep",
                 "sync", "oldstep", "timer_armed",
                 "runtime_aq_last", "logical_aq", "logical_compare"):
        try:
            bemf_state[name] = symbol_address(args.elf, name)
        except RuntimeError:
            continue
    evidence = {"status": "OPEN_NOT_NATIVE_DRIVE", "native_elf": str(args.elf)}
    # The offline recorder is opt-in and never owns QTest/GDB sockets.
    trace = (SitlTraceRecorder(
        elf_sha256=file_sha256(args.elf),
        initial_electrical_degrees=args.initial_electrical_degrees,
        required_sectors=args.sustained_sectors,
        required_integrated_ns=args.sustained_min_integrated_ns)
        if (args.sitl_trace_output or args.sitl_live_port is not None) else None)
    live = args.sitl_live_server
    if args.probe_native_bemf:
        # Diagnose GCC static-symbol suffixes and scope without guessing.
        audit = audit_native_bemf_arm_elf(args.elf)
        evidence["g13b3c_bemf_arm_symbol_audit"] = audit.to_dict()
        if audit.address is not None:
            bemf_state["armed"] = audit.address
        print("G13B3C_NATIVE_ARM_ELF_SYMBOL_AUDIT " +
              json.dumps(audit.to_dict(), sort_keys=True), flush=True)
    with tempfile.TemporaryDirectory(prefix="g13b2e-probe-") as tmp:
        qtpath = str(Path(tmp) / "qtest.sock")
        gdbpath = str(Path(tmp) / "gdb.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(qtpath)
            listener.listen(1)
            listener.settimeout(15)
            # Do not leave QEMU stderr in an undrained PIPE. When the
            # original guest runs beyond initial capture, an emulator
            # diagnostic burst can exhaust the pipe and block *both*
            # QTest readl and the GDB RSP until socket timeouts.
            # A real file preserves the evidence without backpressure.
            qemu_log = open(Path(tmp) / "qemu-stderr.log", "w+b")
            command = [
                str(args.qemu.resolve()), "-M",
                "am13e23019,esc-sim=on,esc-sim-nfault-asserted=off",
                "-kernel", str(args.elf.resolve()), "-S",
                "-display", "none", "-serial", "none", "-monitor", "none",
                "-chardev", f"socket,path={gdbpath},server=on,wait=off,id=gdb0",
                "-gdb", "chardev:gdb0", "-qtest", f"unix:path={qtpath}",
                "-icount", "shift=2,sleep=off,align=off"
            ]
            if args.sim_only_cfg_flash:
                # QEMU generic firmware loader programs factory Cfg
                # into real modeled Flash 0x4000 BEFORE CPU runs.
                # No debugger/QTest write to Guest SRAM or active motor.
                command += [
                    "-device",
                    "loader,file="+str(args.sim_only_cfg_flash.resolve())+
                    ",addr=0x4000,force-raw=on"]
            proc = subprocess.Popen(
                command,stdout=subprocess.DEVNULL,stderr=qemu_log)
            qtconn = None
            armed = set()
            try:
                qtconn, _ = listener.accept()
                qtest = QTest(qtconn)
                for phase in range(3):
                    qtest.write(EXT_OC + 4*phase, 0x10000 | 1000)
                with wait_for_socket(gdbpath, proc) as conn:
                    rsp = RSP(conn)
                    if not rsp.command("?").startswith(("S", "T")):
                        raise RuntimeError("Native original CPU not stopped")
                    if "qXfer:features:read+" not in rsp.command(
                            "qSupported:qXfer:features:read+"):
                        raise RuntimeError("GDB target XML unavailable")
                    if not rsp.command(
                            "qXfer:features:read:target.xml:0,1").startswith(("m<", "l<")):
                        raise RuntimeError("Missing CPU XML")
                    if rsp.command("Qqemu.sstep:1") != "OK":
                        raise RuntimeError("Native virtual-time stepping not enabled")
                    if args.sim_only_cfg_flash:
                        expected=args.sim_only_cfg_flash.read_bytes()
                        # Read actual guest FLASH, not Guest mutable Cfg.
                        # This is the original Rel17 memcpy source.
                        for offset in (0,28,32):
                            actual=rsp.mem32(0x4000+offset)
                            want=int.from_bytes(expected[offset:offset+4],
                                                "little")
                            if actual!=want:
                                raise AssertionError(
                                    "QEMU factory cfg Flash did not provision "
                                    f"0x{0x4000+offset:08x}: "
                                    f"observed=0x{actual:08x} expected=0x{want:08x}")
                        print("PASS_G13B3N_ORIGINAL_FIRMWARE_FLASH_CFG_SOURCE_"
                              "PRE_CPU_READBACK 0x4000",flush=True)
                    _, hardfault, _ = reach_release(
                        rsp, args.elf, args.startup_steps)
                    armed = {*wfi, hardfault}
                    for pc in sorted(armed):
                        add_bp(rsp, pc)
                    try:
                        rendezvous = wait_for_native_main_wfi(
                            rsp, wfi, hardfault, args.slice_ms,
                            args.runtime_slices, stage="B2E_NEUTRAL")
                        neutral = snapshot(rsp, throt)
                        verify(neutral)
                        evidence["neutral_wfi"] = rendezvous
                        if args.wait_native_bemf_calibration:
                            if "calibration_done" not in bemf_state:
                                raise AssertionError(
                                    "Original ELF lacks readable native BEMF "
                                    "calibration_done state")
                            rendezvous = native_wait_for_bemf_calibration(
                                rsp, wfi, rendezvous, hardfault, armed,
                                bemf_state["calibration_done"],
                                args.slice_ms, args.runtime_slices,
                                args.calibration_wfi_visits)
                            evidence["native_bemf_calibration_done"] = rsp.mem32(
                                bemf_state["calibration_done"])
                        for pc in wfi:
                            del_bp(rsp, pc)
                            armed.remove(pc)
                        if args.sim_only_cfg_flash:
                            if rendezvous not in wfi:
                                raise AssertionError("Not an original native WFI")
                            if rendezvous == wfi[1]:
                                # Respect original ARM=1 source policy.
                                # A nonzero DShot sent during ARM cannot
                                # become authorized motor running throttle.
                                unlock = native_original_zero_throttle_arm(
                                    rsp, qtest, wfi=wfi,
                                    hardfault=hardfault,
                                    armed_breakpoints=armed,
                                    throt=throt,
                                    callback=symbols["am13e_app_io_dshot_packet"],
                                    slice_ms=args.slice_ms,
                                    runtime_slices=args.runtime_slices,
                                    bemf_state=bemf_state)
                                evidence["g13b3n_original_zero_arming"] = unlock
                                print("PASS_G13B3N_ORIGINAL_ARM_250MS_AFTER_"
                                      "GENUINE_DSHOT_ZERO " +
                                      json.dumps(unlock,sort_keys=True),
                                      flush=True)
                            elif rendezvous != wfi[0]:
                                raise AssertionError("Unknown original WFI")
                        # Native, non-synthetic DShot600 command. A second
                        # frame is legal only after the external PA26 queue
                        # delivered all 32 genuine zero-throttle edges.
                        # PA26/TIMG4/DMA counters accumulate across genuine
                        # neutral retransmissions. The next positive frame
                        # must contribute its OWN complete 32-edge capture
                        # rather than requiring the all-time totals to be 32.
                        # This preserves the original hardware-backed ingress
                        # and CRC acceptance as strict independent gates.
                        positive_capture_before = qtest.read(PA26 + 0x08)
                        positive_dma_before = qtest.read(PA26 + 0x0c)
                        frame = queue_dshot600_wire(
                            qtest, args.throttle,
                            reset_completed_wave=bool(
                                args.sim_only_cfg_flash and rendezvous==wfi[1]))
                        callback = symbols["am13e_app_io_dshot_packet"]
                        add_bp(rsp, callback)
                        armed.add(callback)
                        # Selected input WWDT was first genuinely fed by
                        # the zero-DShot CRC inside original Rel17. A real
                        # streaming DShot transmitter repeats a throttle
                        # packet. If receiver acquisition misses ONE wave,
                        # permit a bounded NEW physical PA26 frame only.
                        # Never bypass original CRC/ARM, fabricate Guest
                        # SRAM/IRQ, or feed/disable WWDT on the Host.
                        positive_retransmit = bool(
                            args.sim_only_cfg_flash and rendezvous == wfi[1])
                        valid_feeds_start = (
                            rsp.mem32(bemf_state["valid_frame_feeds"])
                            if positive_retransmit else None)
                        last_zero_feed_tick = (
                            evidence["g13b3n_original_zero_arming"]
                            ["original_crc_arm_policy"]
                            ["original_systick_at_zero_callback"]
                            if positive_retransmit else None)
                        max_positive_packets = 4 if positive_retransmit else 1
                        for positive_attempt in range(max_positive_packets):
                            if positive_attempt:
                                # Retry ONLY after the entire last external
                                # 32-edge physical waveform reached the GPIO
                                # and DMA; cumulative counters are expected.
                                wave_ok = (
                                    qtest.read(WAVE + 0x10) == 0 and
                                    qtest.read(WAVE + 0x08) == 32 and
                                    qtest.read(WAVE + 0x0c) == 32 and
                                    qtest.read(WAVE + 0x14) == 0)
                                last_cap = qtest.read(PA26 + 0x08)
                                last_dma = qtest.read(PA26 + 0x0c)
                                rx_rearm = native_pa26_receiver_rearm_snapshot(
                                    qtest)
                                capture_delta = (last_cap -
                                                 positive_capture_before)
                                dma_delta = last_dma - positive_dma_before
                                if not wave_ok or capture_delta != 32:
                                    raise AssertionError(
                                        "G13B3M cannot requeue incomplete "
                                        "physical PA26 positive waveform")
                                if dma_delta != 32:
                                    # Explicitly record this packet as
                                    # REJECTED, never a CRC/valid-frame
                                    # success. An ordinary DShot stream may
                                    # send a new frame after the ORIGINAL
                                    # firmware detects a desync and rearms
                                    # TIMG4->DMA0 CH2. We observe this native
                                    # register ownership, not repair it.
                                    print(
                                        "G13B3M_REJECTED_PARTIAL_DMA_PHYSICAL_FRAME " +
                                        json.dumps({
                                            "physical_capture_delta": capture_delta,
                                            "dma_delta": dma_delta,
                                            "native_receiver": rx_rearm,
                                            "counted_as_valid_frame": False,
                                            "host_guest_writes": False,
                                        }, sort_keys=True), flush=True)
                                    if (dma_delta < 0 or dma_delta >= 32 or
                                            not rx_rearm[
                                                "source_owned_fresh_rx_buffer"]):
                                        raise AssertionError(
                                            "G13B3M partial DMA was NOT "
                                            "naturally rearmed by original "
                                            "Guest; strict fail closed")
                                elif not rx_rearm["source_owned_fresh_rx_buffer"]:
                                    raise AssertionError(
                                        "G13B3M even a complete wire frame "
                                        "must wait for original DMA RX rearm")
                                if (rsp.mem32(throt) != 0 or
                                        rsp.mem32(bemf_state["valid_frame_feeds"])
                                        != valid_feeds_start):
                                    raise AssertionError(
                                        "G13B3M positive original Guest state "
                                        "changed without observed callback; "
                                        "refuse forged acceptance/retransmission")
                                # 16kHz source clock, conservative bound
                                # strictly before nominal WWDT expiration.
                                elapsed = (
                                    rsp.mem32(bemf_state["tick"]) -
                                    last_zero_feed_tick) & 0xffffffff
                                if elapsed >= 12000:
                                    raise AssertionError(
                                        "G13B3M positive retransmission "
                                        "too late for original WWDT deadline "
                                        f"ticks={elapsed}")
                                positive_capture_before = last_cap
                                positive_dma_before = last_dma
                                repeated = queue_dshot600_wire(
                                    qtest, args.throttle,
                                    reset_completed_wave=True)
                                if repeated != frame:
                                    raise AssertionError(
                                        "G13B3M positive DShot CRC waveform changed")
                                print("G13B3M_PHYSICAL_POSITIVE_DSHOT_RETRANSMISSION " +
                                      json.dumps({
                                          "attempt": positive_attempt + 1,
                                          "frame": repeated,
                                          "elapsed_native_systick_since_zero_crc": elapsed,
                                          "previous_frame_full_32_dma": dma_delta == 32,
                                          "previous_frame_rejected_for_dma_shortfall": dma_delta != 32,
                                          "original_receiver_rearmed": rx_rearm,
                                          "host_guest_writes": False
                                      }, sort_keys=True), flush=True)
                            try:
                                resume_to(
                                    rsp, callback, hardfault,
                                    min(args.slice_ms, 25)
                                    if positive_retransmit else args.slice_ms,
                                    2 if positive_retransmit
                                    else args.runtime_slices,
                                    "NATIVE_DSHOT_CALLBACK")
                                break
                            except AssertionError as exc:
                                if not positive_retransmit:
                                    raise
                                state = observer(rsp)
                                port = {
                                    "attempt": positive_attempt + 1,
                                    "error": str(exc),
                                    "cpu": state,
                                    "guest_throt": rsp.mem32(throt),
                                    "valid_feeds": rsp.mem32(
                                        bemf_state["valid_frame_feeds"]),
                                    "physical_wave_delivered": qtest.read(WAVE + 0x0c),
                                    "pa26_captures_this_packet":
                                        qtest.read(PA26 + 0x08)-positive_capture_before,
                                    "dma_beats_this_packet":
                                        qtest.read(PA26 + 0x0c)-positive_dma_before,
                                    "native_receiver":
                                        native_pa26_receiver_rearm_snapshot(qtest),
                                    "host_guest_writes": False,
                                }
                                print("G13B3M_NATIVE_POSITIVE_RX_ATTEMPT_BLOCKER " +
                                      json.dumps(port, sort_keys=True),
                                      flush=True)
                                # CPU faults, unexpected breakpoints or
                                # exhausted physical attempts are terminal.
                                if ("native guest did not reach" not in str(exc) or
                                        positive_attempt + 1 == max_positive_packets):
                                    raise
                        guest_frame = rsp.reg(0) & 0xffff
                        delivered = rsp.mem32(WAVE + 0x0c)
                        capture = rsp.mem32(PA26 + 0x08)
                        dma = rsp.mem32(PA26 + 0x0c)
                        positive_capture_delta = capture - positive_capture_before
                        positive_dma_delta = dma - positive_dma_before
                        positive_receipt = {
                            "frame": frame,
                            "guest_frame": guest_frame,
                            "physical_wave_delivered_this_packet": delivered,
                            "original_pa26_capture_before": positive_capture_before,
                            "original_pa26_capture_after": capture,
                            "original_pa26_capture_this_packet": positive_capture_delta,
                            "original_dma_beat_before": positive_dma_before,
                            "original_dma_beat_after": dma,
                            "original_dma_beats_this_packet": positive_dma_delta,
                            "guest_writes": False,
                        }
                        evidence.update(frame=frame, guest_frame=guest_frame,
                                        wave_delivered=delivered,
                                        tim_capture=capture, dma_beats=dma,
                                        positive_frame_receipt=positive_receipt)
                        print("G13B3N_ORIGINAL_NATIVE_POSITIVE_RX_FRAME_CAUSAL_DELTA " +
                              json.dumps(positive_receipt, sort_keys=True),
                              flush=True)
                        if (frame != guest_frame or delivered != 32 or
                                positive_capture_delta != 32 or
                                positive_dma_delta != 32):
                            raise AssertionError(
                                "SIM_ONLY command missing its own genuine "
                                "32 PA26/TIMG4/DMA edges: " +
                                json.dumps(positive_receipt, sort_keys=True))
                        ret = rsp.reg(14) & ~1
                        if not 0x6000 <= ret < 0x80000:
                            raise AssertionError("Unexpected native DShot LR")
                        del_bp(rsp, callback)
                        armed.remove(callback)
                        add_bp(rsp, ret)
                        armed.add(ret)
                        resume_to(rsp, ret, hardfault, args.slice_ms,
                                  args.runtime_slices, "NATIVE_DSHOT_CRC")
                        crc_ok = rsp.reg(0)
                        native_throt = rsp.mem32(throt)
                        evidence.update(callback_return=crc_ok,
                                        native_throttle=native_throt)
                        if crc_ok != 1 or native_throt <= 1:
                            raise AssertionError(
                                "Original SIM_ONLY firmware did not accept "
                                "DShot command and update its own throttle")
                        print("G13B2E_ORIGINAL_DSHOT_CRC_ACCEPTED " +
                              json.dumps(evidence, sort_keys=True), flush=True)
                        del_bp(rsp, ret)
                        armed.remove(ret)

                        # No host-authored motor start. Discover first
                        # native motor-output start or fault-reset outcome.
                        for name in ("am13e_motor_output_start",
                                     "am13e_power_stage_enable",
                                     "MCPWM4_IRQHandler", FAULT_FN,
                                     "bemf_fault"):
                            if symbols.get(name) is not None:
                                add_bp(rsp, symbols[name])
                                armed.add(symbols[name])
                        saw_output_start = False
                        saw_gate_call = False
                        for n in range(args.runtime_slices):
                            stop, interrupted = continue_bounded(rsp, args.slice_ms)
                            if not stop.startswith(("S02", "T02", "S05", "T05")):
                                raise RuntimeError(f"G13B2E unexpected stop {stop!r}")
                            state = observer(rsp)
                            current = snapshot(rsp, throt)
                            if state["pc"] == hardfault or state["cfsr"] or state["hfsr"]:
                                evidence.update(status="NATIVE_CPU_FAULT",
                                                cpu=state, runtime=current)
                                raise AssertionError(
                                    "Native SIM_ONLY CPU fault during positive input")
                            if interrupted:
                                if n == args.runtime_slices - 1:
                                    evidence.update(status="NO_NATIVE_START_WITHIN_BOUNDS",
                                                    cpu=state, runtime=current)
                                continue
                            if state["pc"] == symbols["MCPWM4_IRQHandler"]:
                                # The native ET1 carrier-ZERO interrupt is
                                # the only legitimate owner of the driver's
                                # delayed gate release after two ZERO events.
                                if state["ipsr"] != 44:
                                    raise AssertionError(
                                        "MCPWM4 native ISR entry without IRQ28/IPSR44")
                                irq_evidence = pwm_native_event_snapshot(
                                    rsp, args.elf, native_start_zero_counter)
                                evidence["native_mcpwm4_irq_entry"] = irq_evidence
                                # Distinguish a REAL configured ET1 counter
                                # ZERO from a Trip (OST) interrupt sharing
                                # this vector. TI SDK uses ZERO=2, not 0.
                                if (irq_evidence["mcpwm_etsel"] & 0x1f) != 2 or (
                                        irq_evidence["mcpwm_etperiod"] & 7) == 0 or (
                                        irq_evidence["mcpwm_intflag"] & 8) == 0 or (
                                        irq_evidence["mcpwm_tzflags"] &
                                        (0x00020000 | 0x00040000)):
                                    raise AssertionError(
                                        "Native IRQ28 was not a qualified "
                                        "MCPWM4 ET1 TBCTR_ZERO event")
                                print("G13B2E_NATIVE_MCPWM4_IRQ_ENTRY_REAL "
                                      "IPSR=44 ET1_SOURCE=2 INTFLAG_ET1=1", flush=True)
                                del_bp(rsp, state["pc"])
                                armed.remove(state["pc"])
                                continue
                            if (symbols.get("bemf_fault") is not None and
                                    state["pc"] == symbols["bemf_fault"]):
                                caller = (rsp.reg(14) & ~1) - 2
                                context = {
                                    "caller_pc": caller,
                                    "caller_symbol":
                                        native_symbol_location(args.elf, caller),
                                    "firmware_bemf_state": {
                                        name: rsp.mem32(addr)
                                        for name, addr in bemf_state.items()
                                    }
                                }
                                evidence["bemf_fault_context"] = context
                                print("G13B2E_ORIGINAL_BEMF_FAULT_CALLSITE " +
                                      json.dumps(context, sort_keys=True),
                                      flush=True)
                                # Observe only, then permit the genuine
                                # firmware's safety shutdown/reset to run.
                                del_bp(rsp, state["pc"])
                                armed.remove(state["pc"])
                                continue
                            if state["pc"] == symbols[FAULT_FN]:
                                evidence.update(status="NATIVE_SAFETY_FAULT_RESET",
                                                cpu=state, runtime=current)
                                break
                            if state["pc"] == symbols["am13e_motor_output_start"]:
                                saw_output_start = True
                                evidence["start_entry"] = current
                                print("G13B2E_NATIVE_MOTOR_OUTPUT_START_CALLED "
                                      "GUEST_ORIGINAL_FIRMWARE", flush=True)
                                del_bp(rsp, state["pc"])
                                armed.remove(state["pc"])
                                preconditions = trace_original_start_preconditions(
                                    rsp, symbols, armed, hardfault,
                                    args.slice_ms, args.runtime_slices)
                                evidence["native_start_preconditions"] = preconditions
                                if preconditions.get("status"):
                                    evidence["status"] = preconditions["status"]
                                    break
                                if preconditions.get("native_start_return") != 1:
                                    evidence["status"] = "NATIVE_MOTOR_START_REJECTED"
                                    break
                                continue
                            if state["pc"] == symbols["am13e_power_stage_enable"]:
                                saw_gate_call = True
                                evidence["gate_enable_entry"] = current
                                pending_zeros = (rsp.mem32(native_start_zero_counter)
                                                 if native_start_zero_counter is not None
                                                 else None)
                                evidence["gate_enable_pending_zeros"] = pending_zeros
                                if not saw_output_start:
                                    raise AssertionError(
                                        "Gate enable reached without native "
                                        "motor output start")
                                if (state["ipsr"] != 44 or
                                        "native_mcpwm4_irq_entry" not in evidence or
                                        pending_zeros != 0 or
                                        current["tzflags"]):
                                    raise AssertionError(
                                        "Native Gate enable not causally owned "
                                        "by two real zero IRQs with clear Trip")
                                print("G13B2E_NATIVE_GATE_ENABLE_CALLED "
                                      "GUEST_ORIGINAL_FIRMWARE "
                                      "IPSR=44 TWO_ZERO_EVENTS_CONSUMED=1", flush=True)
                                ret_gate = rsp.reg(14) & ~1
                                if not 0x6000 <= ret_gate < 0x80000:
                                    raise AssertionError(
                                        "Gate enable LR invalid")
                                del_bp(rsp, state["pc"])
                                armed.remove(state["pc"])
                                add_bp(rsp, ret_gate)
                                armed.add(ret_gate)
                                resume_to(rsp, ret_gate, hardfault, args.slice_ms,
                                          args.runtime_slices, "NATIVE_GATE_RETURN")
                                after = snapshot(rsp, throt)
                                connected = gate_and_pads_connected(
                                    rsp.mem32, gate_active_level=1)
                                # G13B3A observes the six *guest-authored*
                                # PWM outputs and native physical Gate/Trip
                                # state; it never writes PWM or BEMF.
                                native_pwm = observe_original_pwm(
                                    qtest.read, gate_active_level=1)
                                evidence["g13b3a_native_pwm"] = native_pwm.to_dict()
                                bemf_cfg = None
                                if args.probe_native_bemf and (
                                        "selected_code" in bemf_state and
                                        "armed" in bemf_state):
                                    selected = rsp.mem32(bemf_state["selected_code"])
                                    arm_state = rsp.mem32(bemf_state["armed"])
                                    evidence["g13b3c_native_armed_raw"] = arm_state
                                    bemf_cfg = observe_original_bemf_route(
                                        qtest.read, selected_code=selected,
                                        native_armed=(arm_state == 1))
                                    evidence["g13b3c_bemf_readiness"] = (
                                        bemf_cfg.to_dict())
                                    print("G13B3C_NATIVE_BEMF_ARM_READ_ONLY " +
                                          json.dumps(bemf_cfg.to_dict(),
                                                     sort_keys=True), flush=True)
                                elif args.probe_native_bemf:
                                    missing = [
                                        x for x in ("selected_code", "armed")
                                        if x not in bemf_state
                                    ]
                                    print("G13B3C_NATIVE_BEMF_ARM_UNOBSERVABLE "
                                          "no false Ready claim; missing="
                                          + ",".join(missing), flush=True)
                                if args.probe_native_plant_seed:
                                    # Purely synthetic G13A test motor, never
                                    # a Quanta production winding/BOM value.
                                    sim_motor = VirtualBLDC(MotorParameters(
                                        vbus_v=24.0,
                                        phase_resistance_ohm=.3,
                                        phase_inductance_h=.002,
                                        bemf_constant_v_per_rad_s=.02,
                                        torque_constant_nm_per_a=.02,
                                        inertia_kg_m2=1e-6,
                                        viscous_friction_nm_per_rad_s=.0001,
                                        load_torque_nm=0,
                                        pole_pairs=7))
                                    sim_frontend = AnalogFrontend(
                                        reference_v=3.3,
                                        zero_bemf_bias_v=1.65,
                                        input_gain_v_per_bemf_v=.02)
                                    if not native_pwm.acceptable_for_plant:
                                        raise AssertionError(
                                            "Cannot seed a virtual motor from "
                                            "unqualified original PWM: "
                                            + native_pwm.reason)
                                    seed = one_native_pwm_period(
                                        sim_motor, sim_frontend, qtest.read,
                                        gate_active_level=1,
                                        timer_hz=100_000_000)
                                    evidence["g13b3b_plant_seed"] = asdict(seed)
                                    print("G13B3B_ORIGINAL_PWM_ONE_PERIOD_PLANT_SEED " +
                                          json.dumps(asdict(seed),
                                                     sort_keys=True), flush=True)
                                    # QTest writes NO BEMF, ADC, PWM or guest SRAM.
                                    # The motor sample is a standalone physical
                                    # feasibility preflight, NOT live feedback.
                                    if args.require_native_plant_seed and (
                                            not seed.motor.drive_enabled or
                                            seed.motor.mechanical_rpm <= 0 or
                                            not any(abs(i) > 0 for i in
                                                    seed.motor.phase_currents_a)):
                                        raise AssertionError(
                                            "Original output did not move "
                                            "simulated motor in one carrier")
                                    if args.require_native_plant_seed:
                                        print("PASS_G13B3B_GUEST_PWM_TO_ONE_PERIOD "
                                              "VIRTUAL_BLDC_NO_FEEDBACK_INJECTION",
                                              flush=True)
                                if args.probe_native_pwm:
                                    print("G13B3A_NATIVE_OUTPUT_READ_ONLY " +
                                          json.dumps(native_pwm.to_dict(),
                                                     sort_keys=True), flush=True)
                                evidence.update(gate_return=rsp.reg(0),
                                                gate_connected=connected,
                                                gate_post=after,
                                                status="NATIVE_GATE_ON" if connected
                                                and rsp.reg(0) == 1 and
                                                after["pwm_running"] and
                                                after["perclkcr"] & 1 and
                                                not after["tzflags"] else
                                                "NATIVE_GATE_NOT_FULLY_AUTHORIZED")
                                if args.require_native_pwm and (
                                        not native_pwm.acceptable_for_plant):
                                    raise AssertionError(
                                        "G13B3A native output is not yet "
                                        "physically qualified for the VirtualBLDC: "
                                        + native_pwm.reason)
                                if args.require_native_bemf_arm:
                                    # Guest SRAM + CMPSS/ECAP route and hardware
                                    # Gate/Trip, all read only; NO QTest BEMF.
                                    if (evidence["status"] != "NATIVE_GATE_ON"
                                            or not native_pwm.acceptable_for_plant
                                            or bemf_cfg is None
                                            or not bemf_cfg.channel_ready_for_voltage_samples):
                                        raise AssertionError(
                                            "G13B3C native BEMF arm not "
                                            "qualified; fail closed: "
                                            + (bemf_cfg.reason if bemf_cfg else
                                               "guest state unobservable"))
                                    print(
                                        "PASS_G13B3C_NATIVE_BEMF_CAPTURE_ARM "
                                        "GUEST_OWNED_ELF_SYMBOL_AND_REAL_REGISTERS "
                                        "NOT_CAPTURE_IRQ_NOT_CLOSED_LOOP",
                                        flush=True)
                                if args.probe_native_sustained_loop:
                                    if evidence["status"] != "NATIVE_GATE_ON":
                                        raise AssertionError(
                                            "Native sustained motor needs original Gate ON")
                                    loop_result = probe_native_sustained_power_feedback(
                                        rsp, qtest, bemf_state=bemf_state,
                                        armed_breakpoints=armed, wfi=wfi,
                                        hardfault=hardfault,
                                        slice_ms=args.slice_ms,
                                        runtime_slices=args.runtime_slices,
                                        max_visits=args.sustained_wfi_visits,
                                        required_sectors=args.sustained_sectors,
                                        require_sim_only_cfg=(
                                            args.require_native_sustained_loop),
                                        initial_electrical_degrees=(
                                            args.initial_electrical_degrees),
                                         required_integrated_ns=(
                                             args.sustained_min_integrated_ns),
                                         trace=trace, live=live)
                                    evidence["g13b3l_native_sustained_loop"] = (
                                        loop_result)
                                    if args.require_native_sustained_loop and (
                                            not loop_result.get("qualified")):
                                        raise AssertionError(
                                            "G13B3L sustained original native "
                                            "powered six-sector loop remains OPEN: "
                                            + json.dumps(loop_result))
                                if args.require_native_no_bemf_timeout:
                                    if evidence["status"] != "NATIVE_GATE_ON":
                                        raise AssertionError(
                                            "No-feedback timeout requires native Gate ON")
                                    timeout_evidence = observe_original_no_bemf_timeout(
                                        rsp, qtest, bemf_state=bemf_state,
                                        armed_breakpoints=armed, wfi=wfi,
                                        hardfault=hardfault,
                                        slice_ms=args.slice_ms,
                                        runtime_slices=args.runtime_slices,
                                        max_visits=args.no_bemf_timeout_visits)
                                    evidence["g13b3i_original_no_bemf_timeout"] = (
                                        timeout_evidence)
                                if args.probe_native_timeline:
                                    if evidence["status"] != "NATIVE_GATE_ON":
                                        raise AssertionError(
                                            "Native timeline needs original Gate ON")
                                    # This *additional* plant starts at the
                                    # measured Gate return and NEVER writes
                                    # BEMF/IRQ/PWM or advances QEMU clock.
                                    timeline_motor = VirtualBLDC(MotorParameters(
                                        vbus_v=24.0,
                                        phase_resistance_ohm=.3,
                                        phase_inductance_h=.002,
                                        bemf_constant_v_per_rad_s=.02,
                                        torque_constant_nm_per_a=.02,
                                        inertia_kg_m2=1e-6,
                                        viscous_friction_nm_per_rad_s=.0001,
                                        load_torque_nm=0,
                                        pole_pairs=7))
                                    summary = collect_native_pwm_timeline(
                                        rsp, qtest, hardfault=hardfault,
                                        armed_breakpoints=armed, wfi=wfi,
                                        bemf_state=bemf_state,
                                        slice_ms=args.slice_ms,
                                        runtime_slices=args.runtime_slices,
                                        visits=args.timeline_visits,
                                        motor=timeline_motor,
                                        require_capture=args.require_native_bemf_capture,
                                        probe_commutation=args.probe_native_commutation,
                                        require_early_rejection=(
                                            args.require_native_early_rejection),
                                        extended_feedback_visits=(
                                            args.extended_native_feedback_visits),
                                        frontend=(AnalogFrontend(
                                            reference_v=3.3,
                                            zero_bemf_bias_v=1.65,
                                            input_gain_v_per_bemf_v=.02)
                                            if args.require_native_bemf_injection
                                            else None))
                                    evidence["g13b3d_native_timeline"] = summary
                                    print("G13B3D_NATIVE_RUNTIME_TIMELINE_READ_ONLY " +
                                          json.dumps(summary, sort_keys=True),
                                          flush=True)
                                    if args.probe_native_commutation:
                                        verdict = summary.get("original_commutation", {})
                                        if verdict.get("native_timg12_commutation_proved"):
                                            print("PASS_G13B3G_ORIGINAL_ECAP1_TO_"
                                                  "TIMG12_TO_SIX_PWM_CHANGE "
                                                  "NOT_SUSTAINED_CLOSED_LOOP",
                                                  flush=True)
                                        elif args.require_native_commutation:
                                            raise AssertionError(
                                                "G13B3G original ELF did not "
                                                "accept/schedule/service "
                                                "plant BEMF event: " +
                                                json.dumps(verdict))
                                        else:
                                            print("G13B3G_OPEN_NOT_NATIVE_"
                                                  "COMMUTATION_QUALIFIED " +
                                                  json.dumps(verdict),
                                                  flush=True)
                                    if args.require_native_bemf_capture:
                                        print("PASS_G13B3F_NATIVE_CMPSS0_ECAP1_"
                                              "CAP1_ORIGINAL_ISR_FROM_PLANT_"
                                              "BEMF_NOT_COMMUTATION",
                                              flush=True)
                                    if args.require_native_bemf_injection:
                                        print("PASS_G13B3E_NATIVE_PLANT_DERIVED_"
                                              "THREE_PHASE_BEMF_STIMULUS "
                                              "NOT_ECAP_IRQ_NOT_CLOSED_LOOP",
                                              flush=True)
                                    if args.require_native_timeline:
                                        print("PASS_G13B3D_NATIVE_CONTINUOUS_PWM "
                                              "ECAP_CLOCK_TIME_COUPLED_PLANT "
                                              "NO_BEMF_FEEDBACK_INJECTION",
                                              flush=True)
                                if (args.trip_after_native_gate or
                                        args.trip_after_native_bemf_injection):
                                    if args.trip_after_native_bemf_injection:
                                        injected = summary.get("bemf_injection", {})
                                        if (injected.get("sample_count", 0) < 5 or
                                                injected.get("nonneutral_samples", 0) < 1):
                                            raise AssertionError(
                                                "No active physically derived BEMF "
                                                "before live coupled fault")
                                    if evidence["status"] != "NATIVE_GATE_ON":
                                        raise AssertionError(
                                            "Post-drive Trip requires qualified "
                                            "original Firmware Gate/PWM ON")
                                    # Independent physical nFAULT input
                                    # changes while the original ARM33 core
                                    # is GDB-halted *after* its gate function
                                    # returned. No guest CSR/IRQ/gate/PWM
                                    # fields are overwritten.
                                    qtest.write(EXT_OC + 0x18, 1)
                                    physical_tz = qtest.read(PWM4 + 0xb0)
                                    physical_irq = qtest.read(PWM4 + 0x94)
                                    from tools.virtual_bldc import OBS_BASE
                                    output_levels = qtest.read(OBS_BASE + 0x10)
                                    output_counts = [
                                        qtest.read(OBS_BASE + 0x18 + 4 * i)
                                        for i in range(6)
                                    ]
                                    evidence["post_gate_physical_trip"] = {
                                        "input_nfault_asserted": qtest.read(
                                            EXT_OC + 0x18),
                                        "ost_status": physical_tz,
                                        "interrupt_flags": physical_irq,
                                        "effective_levels": output_levels,
                                        "effective_high_ticks": output_counts,
                                    }
                                    if ((physical_tz & 0x20000) != 0x20000 or
                                            not physical_irq & 4 or
                                            output_levels != 0 or
                                            any(output_counts)):
                                        raise AssertionError(
                                            "Real nFAULT did not asynchronously "
                                            "latch OST2 and force ALL SIX "
                                            "physical MCPWM outputs LOW "
                                            "before native ARM executes")
                                    print(
                                        "PASS_G13B2E_NATIVE_GATE_ON_EXTERNAL_NFAULT "
                                        "ASYNC_OST2_ALL_SIX_PWM_LOW_CPU_HALTED",
                                        flush=True)
                                    # G13B3H: timeline already removed the
                                    # Gate-return breakpoint, and still owns
                                    # original main-WFI stops. Clear only
                                    # debugger breakpoints; NEVER write CPU
                                    # masks/state or original guest code.
                                    for pc in sorted(armed - {hardfault}):
                                        del_bp(rsp, pc)
                                        armed.remove(pc)
                                    # The native-timeline probe removed the
                                    # original fault-reset *debugger* BP.
                                    # Re-install only this observation BP;
                                    # NEVER force a guest PC/IRQ/fault path.
                                    if symbols[FAULT_FN] not in armed:
                                        add_bp(rsp, symbols[FAULT_FN])
                                        armed.add(symbols[FAULT_FN])
                                    # Let the original ISR finish executing
                                    # its nFAULT readiness and nonreturning
                                    # fault-reset policy. No host mutation of
                                    # PRIMASK, main stack, or ISR return.
                                    resume_to(
                                        rsp, symbols[FAULT_FN], hardfault,
                                        args.slice_ms, args.runtime_slices,
                                        "POST_GATE_NFAULT_NATIVE_SHUTDOWN")
                                    shutdown = snapshot(rsp, throt)
                                    evidence["post_gate_native_shutdown"] = shutdown
                                    if (shutdown["pb13_dout"] != 0 or
                                            not shutdown["tzflags"] & 0x20000 or
                                            shutdown["cfsr"] or shutdown["hfsr"]):
                                        raise AssertionError(
                                            "Original nFAULT shutdown did not "
                                            "deassert PB13 with OST2 latched")
                                    evidence["status"] = (
                                        "NATIVE_GATE_ON_THEN_NFAULT_SHUTDOWN")
                                    print(
                                        "PASS_G13B2E_ORIGINAL_FIRMWARE_POST_GATE "
                                        "NFAULT_SHUTDOWN_WITH_HARDWARE_OST2",
                                        flush=True)
                                    if args.trip_after_native_bemf_injection:
                                        evidence["g13b3h_live_bemf_fault"] = {
                                            "coupled_bemf_sample_count":
                                                injected["sample_count"],
                                            "nonneutral_bemf_samples":
                                                injected["nonneutral_samples"],
                                            "physical_nfault_ost2": True,
                                            "original_firmware_shutdown": True,
                                            "sensorless_closed_loop_proved": False,
                                        }
                                        print(
                                            "PASS_G13B3H_PHYSICAL_NFAULT_WHILE_"
                                            "PLANT_BEMF_INJECTED_ORIGINAL_"
                                            "FIRMWARE_SHUTDOWN "
                                            "NOT_SUSTAINED_CLOSED_LOOP",
                                            flush=True)
                                break
                            raise AssertionError(
                                f"Unexpected native breakpoint PC=0x{state['pc']:08x}")
                        evidence["saw_output_start"] = saw_output_start
                        evidence["saw_gate_call"] = saw_gate_call
                        evidence["native_pwm_zero_irq"] = pwm_native_event_snapshot(
                            rsp, args.elf, native_start_zero_counter)
                        print("G13B2E_DIAGNOSTIC " +
                              json.dumps(evidence, sort_keys=True), flush=True)
                        if args.require_bemf_reject:
                            pre = evidence.get("native_start_preconditions", {})
                            if (evidence["status"] != "NATIVE_MOTOR_START_REJECTED" or
                                    pre.get("am13e_app_motor_nfault_trip_ready_return") != 1 or
                                    pre.get("am13e_app_motor_bemf_reference_start_ready_return") != 0 or
                                    pre.get("native_start_return") != 0 or
                                    evidence["saw_gate_call"] or
                                    evidence["start_entry"]["pb13_dout"] != 0):
                                raise AssertionError(
                                    "Uncalibrated BEMF Reference failed to "
                                    "reject motor startup independently of "
                                    "healthy native nFAULT Trip")
                            print("PASS_G13B2E_ORIGINAL_ELF_UNCALIBRATED_BEMF "
                                  "REJECTS_MOTOR_START_GATE_OFF", flush=True)
                        elif evidence["status"] in (
                                "NATIVE_GATE_ON",
                                "NATIVE_GATE_ON_THEN_NFAULT_SHUTDOWN"):
                            print("PASS_G13B2E_ORIGINAL_SIM_ONLY_GATE_PWM_AUTHORIZATION "
                                  "NOT_SENSORLESS_CLOSED_LOOP", flush=True)
                        elif args.require_drive:
                            raise AssertionError(
                                "Native original-ELF Gate/PWM not authorized: "
                                + evidence["status"])
                        else:
                            print("G13B2E_OPEN_NO_POSITIVE_NATIVE_DRIVE_PROOF",
                                  flush=True)
                    finally:
                        # Keep the original failure visible if the
                        # simulator's control sockets became unresponsive.
                        # A cleanup failure must not replace the real
                        # triggering QTest/GDB exception in traceback.
                        primary_failure = sys.exc_info()[1]
                        for pc in sorted(armed, reverse=True):
                            try:
                                del_bp(rsp, pc)
                            except (TimeoutError, ConnectionError,
                                    OSError, RuntimeError) as cleanup_error:
                                if primary_failure is None:
                                    raise
                                print("G13B3_NATIVE_BP_CLEANUP_AFTER_FAILURE " +
                                      repr(cleanup_error), flush=True)
                                break
            finally:
                # Persist an opt-in partial trace even when the strict native
                # probe fails; do not turn missing motor evidence into PASS.
                if trace is not None and args.sitl_trace_output is not None:
                    primary = sys.exc_info()[1]
                    try:
                        trace.write(args.sitl_trace_output,
                                    error_type=(type(primary).__name__
                                                if primary is not None else None))
                        print("E62_SITL_NATIVE_TRACE_RECORDED path=" +
                              str(args.sitl_trace_output) +
                              " samples=" + str(len(trace.samples)) +
                              " events=" + str(len(trace.events)), flush=True)
                    except Exception as trace_error:
                        if primary is None:
                            raise
                        print("E62_SITL_TRACE_WRITE_FAILED_AFTER_NATIVE_ERROR " +
                              repr(trace_error), flush=True)
                if live is not None:
                    primary = sys.exc_info()[1]
                    stream = live.hub.snapshot()
                    count = len(trace.samples) if trace is not None else 0
                    if stream["seq"] != count:
                        if primary is None:
                            raise AssertionError(
                                "Live WFI telemetry dropped a publisher frame")
                        print("E62_SITL_LIVE_PUBLISH_INCOMPLETE_AFTER_NATIVE_ERROR "
                              f"packets={stream['seq']} native={count}",
                              flush=True)
                    live.hub.finish(
                        native_result=(trace.native_result if trace is not None
                                       else None),
                        error_type=(type(primary).__name__
                                    if primary is not None else None))
                    print("E62_SITL_LIVE_CAPTURED "
                          f"frames={stream['seq']} "
                          f"buffer_truncated={stream['truncated']} "
                          "extra_guest_queries=0", flush=True)
                # Transport-only counters: observational profiling, not
                # motor state, Guest registers or altered acceptance gates.
                if "rsp" in locals() and "qtest" in locals():
                    print("G13B3_NATIVE_TRANSPORT_PROFILE " +
                          json.dumps({
                              "rsp_commands": rsp.command_count,
                              "rsp_socket_recv_calls": rsp.recv_calls,
                              "rsp_bytes_received": rsp.recv_bytes,
                              "qtest_commands": qtest.command_count,
                              "qtest_mmio_reads": qtest.read_count,
                              "qtest_mmio_writes": qtest.write_count,
                              "host_guest_register_writes": False,
                              "scope": "TRANSPORT_DIAGNOSTIC_ONLY"
                          }, sort_keys=True), flush=True)
                if qtconn is not None:
                    qtconn.close()
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                # Read log after process termination; no QEMU can block
                # on an undrained pipe while original firmware is live.
                try:
                    qemu_log.flush()
                    qemu_log.seek(0, 2)
                    log_size = qemu_log.tell()
                    if args.artifact is not None and log_size:
                        from shutil import copyfile
                        destination = args.artifact.with_suffix(
                            ".qemu-stderr.log")
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        copyfile(qemu_log.name, destination)
                    if log_size and (args.extended_native_feedback_visits
                                     or proc.returncode not in (0, -15)):
                        qemu_log.seek(max(0, log_size - 8000))
                        print("G13B3_QEMU_DIAGNOSTIC_STDERR "
                              f"bytes={log_size} " +
                              qemu_log.read().decode(
                                  "utf-8", errors="replace"),
                              flush=True)
                finally:
                    qemu_log.close()
    if args.artifact:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(evidence, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    p.add_argument("--throttle", type=int, default=1000)
    p.add_argument("--objdump", default="arm-none-eabi-objdump")
    p.add_argument("--startup-steps", type=int, default=32768)
    p.add_argument("--slice-ms", type=int, default=300)
    p.add_argument("--runtime-slices", type=int, default=20)
    p.add_argument("--require-drive", action="store_true")
    p.add_argument("--probe-native-pwm", action="store_true",
                   help="Read-only original six MCPWM duties and safety "
                        "qualification at Native Gate on, no motor feedback")
    p.add_argument("--require-native-pwm", action="store_true",
                   help="Opt-in: assert native six-output nonzero phase "
                        "drive and actual Gate/PINCM/power/Trip safety")
    p.add_argument("--probe-native-bemf", action="store_true",
                   help="Read-only original CMPSS0/ECAP1 selected phase, "
                        "DAC, capture arm and native IRQ config")
    p.add_argument("--require-native-bemf-arm", action="store_true",
                   help="Strict G13B3C native armed/phase/CMPSS0/ECAP1 "
                        "and physical PWM/Gate/Trip read-only gate; no IRQ")
    p.add_argument("--probe-native-plant-seed", action="store_true",
                   help="G13B3B: integrate *one* guest PWM carrier into "
                        "explicitly synthetic test motor; NEVER feed BEMF")
    p.add_argument("--require-native-plant-seed", action="store_true",
                   help="Gate one native PWM carrier -> independent host "
                        "motor current and motion, with no feedback injection")
    p.add_argument("--probe-native-timeline", action="store_true",
                   help="G13B3D: sampled read-only native PWM/ECAP1 time "
                        "coupling into independent host VirtualBLDC; "
                        "no QEMU clock manipulation or BEMF injection")
    p.add_argument("--require-native-timeline", action="store_true",
                   help="Require multiple real native WFI PWM observations "
                        "with bounded ECAP intervals and motor progress")
    p.add_argument("--timeline-visits", type=int, default=4)
    p.add_argument("--probe-native-sustained-loop", action="store_true",
                   help="G13B3L original firmware multi-CAP1/TIMG12/real "
                        "powered PWM with physically gated VirtualBLDC")
    p.add_argument("--require-native-sustained-loop", action="store_true",
                   help="Strict native original firmware SIX accepted powered "
                        "commutations; fail closed if unfinished")
    p.add_argument("--sustained-wfi-visits", type=int, default=1024)
    p.add_argument("--sustained-sectors", type=int, default=6)
    p.add_argument("--sustained-min-integrated-ns", type=int, default=0,
                   help="G13B3M source WFI/ECAP powered duration; 0 for six-step baseline")
    p.add_argument("--initial-electrical-degrees", type=float, default=0.0,
                   help="G13B3L only, explicit SIM_ONLY stationary rotor "
                        "magnetic phase relative to initial six-step sector; "
                        "never an initial RPM or synthetic BEMF stimulus")
    p.add_argument("--require-native-no-bemf-timeout",
                   action="store_true",
                   help="G13B3I original native ECAP/SysTick no-valid-BEMF "
                        "timeout; no analog/MMIO/IRQ/PWM stimulus written")
    p.add_argument("--no-bemf-timeout-visits", type=int, default=640)
    p.add_argument("--require-native-early-rejection", action="store_true",
                   help="G13B3G negative control: only a real early "
                        "CAP1+ISR may be rejected by original Rel17, "
                        "with no TIMG12 schedule and native arm preserved")
    p.add_argument("--extended-native-feedback-visits",
                   type=int, default=0,
                   help="Continue original guest WFI+ECAP clock and actual "
                        "VirtualBLDC analog feedback after the first "
                        "early-rejected native CAP1; bounded, no forced edge")
    p.add_argument("--probe-native-commutation", action="store_true",
                   help="G13B3G: inspect original guest TIMG12 scheduling "
                        "and service after physically derived ECAP1 CAP1; "
                        "diagnostic is explicitly OPEN if guest rejects")
    p.add_argument("--require-native-commutation", action="store_true",
                   help="Require original guest ISR schedules and services "
                        "TIMG12 plus a distinct physically qualified native "
                        "six PWM output after model-driven BEMF")
    p.add_argument("--require-native-bemf-capture", action="store_true",
                   help="G13B3F: require modeled BEMF threshold crossing "
                        "followed by hardware CAP1 and original IRQ counter")
    p.add_argument("--require-native-bemf-injection", action="store_true",
                   help="G13B3E: inject only physically calculated U/V/W "
                        "voltages via QEMU SIM_ONLY MMIO after qualified "
                        "native Gate/PWM/ECAP/BEMF arm observations")
    p.add_argument("--trip-after-native-bemf-injection",
                   action="store_true",
                   help="Fault regression: after qualified multiple native "
                        "BEMF voltage samples, apply real external nFAULT "
                        "and require asynchronous OST2 + guest fault reset")
    p.add_argument("--trip-after-native-gate", action="store_true",
                   help="After native Gate ON, assert only external nFAULT "
                        "while CPU halted; require asynchronous OST2 "
                        "all-six-low and original Firmware shutdown")
    p.add_argument("--wait-native-bemf-calibration", action="store_true",
                   help="Before DShot, wait for real original ECAP/SysTick "
                        "calibration_done via genuine WFI, no SRAM writes")
    p.add_argument("--calibration-wfi-visits", type=int, default=24)
    p.add_argument("--require-bemf-reject", action="store_true",
                   help="Require native uncalibrated BEMF refuses start, "
                        "while nFAULT is healthy; no spoofed ready state")
    p.add_argument("--sim-only-cfg-flash",type=Path,
                   help="G13B3N pre-boot factory Cfg Flash 0x4000 loader; "
                        "strict SIM_ONLY only, not Guest RAM or production Flash")
    p.add_argument("--artifact", type=Path)
    p.add_argument("--sitl-trace-output", type=Path,
                   help="Optional offline WebGUI WFI trace JSON. Reuses "
                        "existing native samples; no new Guest/MMIO queries")
    p.add_argument("--sitl-live-port", type=int, metavar="PORT",
                   help="Opt-in read-only localhost SSE dashboard port; "
                        "0 selects an available loopback port")
    p.add_argument("--sitl-live-hold", action="store_true",
                   help="Keep the browser dashboard open after native exit "
                        "until Ctrl-C (interactive terminals only)")
    a = p.parse_args()
    if not a.qemu.is_file() or not a.elf.is_file():
        p.error("Missing QEMU or genuine SIM_ONLY ELF")
    if a.require_native_sustained_loop and not a.sim_only_cfg_flash:
        p.error("Strict G13B3L requires provisioned original Flash Cfg")
    if a.sim_only_cfg_flash:
        if (not a.require_native_sustained_loop or
            not a.sim_only_cfg_flash.is_file() or
            not 256 <= a.sim_only_cfg_flash.stat().st_size <= 4096):
            p.error("SIM_ONLY Flash factory Cfg only with strict native "
                    "loop and a bounded binary image")
    if not 1 <= a.calibration_wfi_visits <= 64:
        p.error("BEMF calibration wait visits must be 1..64")
    if (a.trip_after_native_bemf_injection and
            (not a.require_native_bemf_injection or
             a.require_native_bemf_capture or a.trip_after_native_gate)):
        p.error("--trip-after-native-bemf-injection requires positive "
                "native BEMF injection; incompatible with capture proof "
                "or duplicate gate trip")
    if a.trip_after_native_gate and (
            not a.require_drive or not a.wait_native_bemf_calibration or
            a.require_bemf_reject):
        p.error("--trip-after-native-gate requires --require-drive "
                "and --wait-native-bemf-calibration; incompatible "
                "with BEMF negative test")
    if a.require_native_pwm and not a.require_drive:
        p.error("--require-native-pwm needs --require-drive")
    if a.require_native_pwm:
        a.probe_native_pwm = True
    if a.require_native_bemf_arm:
        if (not a.require_drive or not a.require_native_pwm or
                not a.wait_native_bemf_calibration or a.require_bemf_reject):
            p.error("--require-native-bemf-arm requires --require-drive "
                    "--require-native-pwm --wait-native-bemf-calibration")
        a.probe_native_bemf = True
    if (not math.isfinite(a.initial_electrical_degrees) or
            not -180 <= a.initial_electrical_degrees <= 180):
        p.error("Explicit initial rotor electrical pose must be finite and within +/-180 degrees")
    if a.initial_electrical_degrees and not a.probe_native_sustained_loop and not a.require_native_sustained_loop:
        p.error("Nonzero initial rotor angle only belongs to G13B3L sustained SIM_ONLY motor")
    if not 6 <= a.sustained_sectors <= 24:
        p.error("--sustained-sectors must be 6..24")
    if not 0 <= a.sustained_min_integrated_ns <= 2_000_000_000:
        p.error("Native powered ECAP integration bound out of range")
    if a.sustained_min_integrated_ns and (
            not a.require_native_sustained_loop or a.sustained_sectors < 12):
        p.error("G13B3M timed endpoint requires strict >=12 native sectors")
    if not 64 <= a.sustained_wfi_visits <= 4096:
        p.error("--sustained-wfi-visits must be 64..4096")
    if a.require_native_sustained_loop:
        a.probe_native_sustained_loop = True
    if a.sitl_trace_output and (not a.probe_native_sustained_loop or
            (a.artifact is not None and
             a.sitl_trace_output.resolve() == a.artifact.resolve())):
        p.error("SITL trace requires native sustained loop and a distinct "
                "output path from --artifact")
    if a.sitl_live_hold and a.sitl_live_port is None:
        p.error("--sitl-live-hold requires --sitl-live-port")
    if a.sitl_live_port is not None:
        if not a.probe_native_sustained_loop or not 0 <= a.sitl_live_port <= 65535:
            p.error("--sitl-live-port requires native sustained loop and port 0..65535")
        if a.sitl_live_hold and not sys.stdin.isatty():
            p.error("--sitl-live-hold requires an interactive terminal")
    if a.probe_native_sustained_loop and (
            not a.require_native_bemf_arm or
            a.probe_native_timeline or a.require_native_no_bemf_timeout or
            a.trip_after_native_gate or a.trip_after_native_bemf_injection):
        p.error("--probe-native-sustained-loop requires real original "
                "Gate/PWM/BEMF arm, not the legacy one-event timeline "
                "or fault/timeout injection probe")
    if not 520 <= a.no_bemf_timeout_visits <= 1024:
        p.error("--no-bemf-timeout-visits must be 520..1024")
    if a.require_native_no_bemf_timeout:
        if (not a.require_native_bemf_arm or
                a.require_native_bemf_injection or
                a.probe_native_commutation or
                a.require_native_bemf_capture or
                a.trip_after_native_gate or
                a.trip_after_native_bemf_injection):
            p.error("--require-native-no-bemf-timeout needs positive "
                    "native Gate/PWM/BEMF arm but NO feedback/Trip injection")
    if not 0 <= a.extended_native_feedback_visits <= 512:
        p.error("--extended-native-feedback-visits must be 0..512")
    if (a.extended_native_feedback_visits and
            not (a.probe_native_commutation or
                 a.require_native_commutation)):
        p.error("--extended-native-feedback-visits requires "
                "--probe-native-commutation")
    if a.require_native_early_rejection:
        a.require_native_bemf_capture = True
    if a.require_native_commutation:
        a.probe_native_commutation = True
    if a.probe_native_commutation:
        a.require_native_bemf_capture = True
    if a.require_native_bemf_capture:
        a.require_native_bemf_injection = True
    if a.require_native_bemf_injection:
        a.require_native_timeline = True
    if a.require_native_timeline:
        a.probe_native_timeline = True
    if a.probe_native_timeline:
        if (not a.require_native_bemf_arm or
                not a.require_native_pwm or
                a.trip_after_native_gate or a.require_bemf_reject):
            p.error("--probe-native-timeline requires "
                    "--require-native-bemf-arm --require-native-pwm "
                    "and no post-gate trip or BEMF reject")
        if not 3 <= a.timeline_visits <= 8:
            p.error("--timeline-visits must be 3..8")
    if a.require_native_plant_seed:
        a.probe_native_plant_seed = True
    if a.probe_native_plant_seed:
        if not a.require_drive:
            p.error("--probe-native-plant-seed needs --require-drive")
        a.probe_native_pwm = True
    if a.require_drive and a.require_bemf_reject:
        p.error("Cannot simultaneously require positive drive and "
                "an uncalibrated BEMF rejection")
    live = (SitlLiveServer(port=a.sitl_live_port).start()
            if a.sitl_live_port is not None else None)
    a.sitl_live_server = live
    if live is not None:
        print("E62_SITL_LIVE_READ_ONLY_URL " + live.url, flush=True)
    try:
        run(a)
    finally:
        if live is not None:
            error = sys.exc_info()[1]
            # Native six-/twelve-sector probes do not run the separate
            # G13B3M extended gate. Never imply complete CI qualification.
            live.hub.finish(native_result=None,
                            error_type=(type(error).__name__
                                        if error is not None else None))
            if a.sitl_live_hold:
                print("E62_SITL_LIVE_VIEWER_HOLD Ctrl-C to exit (no Guest commands)",
                      flush=True)
                import time
                try:
                    while True:
                        time.sleep(0.5)
                except KeyboardInterrupt:
                    pass
            live.close()


if __name__ == "__main__":
    main()
