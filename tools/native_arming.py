"""Rel17.3 native startup/neutral-arm primitives (historical public API).
No writes to Guest throttle/CRC, no synthetic watchdog progress. This
module depends on original test harness GDB/QTest adapter symbols."""
import json
import re
import subprocess
import sys
from pathlib import Path
_TESTS = str(Path(__file__).resolve().parents[1] / 'tests')
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
from g13b_native_dshot import queue_dshot600_wire, WAVE, PA26, DMA
from g11_exception_lifecycle import observer, add_bp, del_bp, continue_bounded
from g13b_native_wfi import wait_for_native_main_wfi

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






def resolve_original_rel17_wfi_roles(elf, candidates, *, addr2line="arm-none-eabi-addr2line"):
    """Map pinned Rel17.3 ARM/run WFI by ELF DWARF source, NEVER address order.

    src/main.c:910 is the original 250ms zero-throttle ARM loop;
    src/main.c:1194 is the original 1kHz control loop. The exact line
    contracts are tied to the pinned upstream Rel17.3 firmware revision.
    A missing/ambiguous mapping is a hard failure, not an ARM bypass.
    """
    if len(candidates) != 2 or len(set(candidates)) != 2:
        raise AssertionError("Pinned original Rel17 requires two distinct main WFI sites")
    roles = {}
    details = {}
    for pc in candidates:
        result = subprocess.run(
            [addr2line, "-f", "-C", "-i", "-e", str(elf), f"0x{pc:x}"],
            capture_output=True, text=True, check=True, timeout=15)
        lines = result.stdout.strip().splitlines()
        source_roles = set()
        if lines and lines[0].strip() == "am13e_rel17_app_main":
            for line in lines[1:]:
                src_line = line.replace("\\", "/")
                m = re.search(r"/src/main[.]c:(910|1194)(?:[^0-9]|$)", src_line)
                if m:
                    source_roles.add("ARM" if m.group(1) == "910" else "RUNNING")
        details[f"0x{pc:08x}"] = result.stdout.strip().replace("\n", " | ")
        if len(source_roles) != 1:
            raise AssertionError(
                "Cannot prove original Rel17 WFI ARM/run source role: " +
                json.dumps(details, sort_keys=True))
        role = source_roles.pop()
        if role in roles:
            raise AssertionError(
                "Duplicated original Rel17 WFI role: " +
                json.dumps(details, sort_keys=True))
        roles[role] = pc
    if set(roles) != {"RUNNING", "ARM"}:
        raise AssertionError("Missing original Rel17 ARM/run WFI source evidence")
    print("G13B3N_ORIGINAL_WFI_SOURCE_ROLE_MAP " +
          json.dumps({
              "running_wfi_pc": hex(roles["RUNNING"]),
              "arming_wfi_pc": hex(roles["ARM"]),
              "source": "PINNED_REL17_3_ELF_DWARF_MAIN_C_910_1194",
              "wfi_address_order_assumed": False,
              "host_guest_writes": False
          }, sort_keys=True), flush=True)
    # Canonical semantic order for this probe's historical wfi[0]/wfi[1]
    # consumers. Neither caller may infer source role from numeric PC.
    return roles["RUNNING"], roles["ARM"]


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
    if len(wfi) != 2 or wfi[0] == wfi[1]:
        raise AssertionError(
            "Pinned original Rel17 WFI roles must be distinct and source-qualified")
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
