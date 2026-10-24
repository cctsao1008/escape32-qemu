#!/usr/bin/env python3
"""G13B5 opt-in native autonomous SITL: no per-WFI GDB stepping.

QEMU supplies physical PA26 edges and synthetic analog BEMF using its
virtual timers. Guest Cortex-M33 runs continuously; Python polls SIM_ONLY
status and asynchronously samples original Guest telemetry at low rate.
Neither this adapter nor the emulator writes Guest SRAM, PWM, CAP1 or IRQ.
"""
import json
import threading
import time

from g11_exception_lifecycle import observer, del_bp, continue_bounded
from g13b_native_dshot import queue_dshot600_wire
from tools.autonomous_sitl_host import (
    configure_auto, read_auto, native_end_oracle,
    AUTO_RUNNING, AUTO_DONE, AUTO_ERROR,
)
from tools.native_pwm_qualification import observe_original_pwm

def guest_snapshot(read32, addresses):
    return {name: read32(addresses[name])
            for name in ('throt','valid_frame_feeds','step',
                         'captured_events','scheduled','serviced')}


def run_autonomous(args, scenario, evidence, rsp, qtest,
                   hardfault, armed, addresses, wfi):
    """Enter only after physical neutral CRC + genuine 250ms ARM release."""
    for pc in wfi:
        if pc in armed:
            del_bp(rsp, pc)
            armed.remove(pc)
    if armed != {hardfault}:
        raise AssertionError('Autonomous guest must retain ONLY HardFault breakpoint')
    baseline = guest_snapshot(rsp.mem32, addresses)
    if baseline['throt'] != 0:
        raise AssertionError('Original Guest is not neutral after source ARM')
    baseline.update(pa26_capture=qtest.read(0x5ffe0008),
                    pa26_dma=qtest.read(0x5ffe000c))
    initial = configure_auto(qtest, scenario, max_frames=args.max_frames)
    evidence['autonomous'] = {
        'scope': 'QEMU_VIRTUAL_TIMER_DSHOT_AND_ANALOG_GUEST_RUNS_CONTINUOUSLY',
        'stage_source': 'DECLARATIVE_T01_T02_QTEST_CONFIG',
        'startup': initial,
        'before_guest': baseline,
        'host_guest_register_writes': False,
        'guest_wfi_breakpoints_during_runtime': False,
        'telemetry_coherence': 'ASYNC_READS_DIAGNOSTIC_ONLY',
    }
    evidence['telemetry'] = []
    outcome = {}
    def continue_guest():
        try:
            outcome['stop'] = rsp.command('c')
        except Exception as exc:
            outcome['exception'] = str(exc)
    rsp_timeout = rsp.sock.gettimeout()
    rsp.sock.settimeout(args.autonomous_wall_timeout_s + 30)
    thread = threading.Thread(target=continue_guest, daemon=True)
    started = time.monotonic()
    last_log_frames = 0
    last_sample_ms = -1000
    snap = initial
    try:
        thread.start()
        while True:
            if time.monotonic() - started > args.autonomous_wall_timeout_s:
                raise TimeoutError('Bounded host wall-clock timeout before QEMU virtual duration completed')
            if not thread.is_alive() and 'exception' in outcome:
                raise RuntimeError('Original Guest RSP continue failed: '+outcome['exception'])
            snap = read_auto(qtest.read)
            if snap['status'] & AUTO_ERROR:
                raise AssertionError('Autonomous QEMU stimulus error: '+str(snap))
            if snap['status'] & AUTO_DONE:
                break
            if not thread.is_alive():
                raise AssertionError('Original Guest stopped before autonomous QEMU finished: '+
                                     str(outcome))
            if snap['sent'] >= last_log_frames + 1000:
                last_log_frames = snap['sent']
                print('E62_AUTONOMOUS_PROGRESS ' + json.dumps({
                    'frames': snap['sent'], 'target': snap['target_frames'],
                    'guest_elapsed_ms': snap['elapsed_ms'],
                    'bemf_stimulus_transitions': snap['bemf_crossings'],
                }, sort_keys=True), flush=True)
            if snap['elapsed_ms'] >= last_sample_ms + 1000:
                last_sample_ms = snap['elapsed_ms']
                g = guest_snapshot(qtest.read, addresses)
                record = {'sim_elapsed_ms':snap['elapsed_ms'],
                          'sim_dshot_value':snap['last_dshot'],
                          'guest_throt_sample':g['throt'],
                          'guest_valid_crc_feed_total':g['valid_frame_feeds'],
                          'guest_step_sample':g['step'],
                          'guest_cap1_total':g['captured_events'],
                          'guest_timg12_scheduled_total':g['scheduled'],
                          'guest_timg12_serviced_total':g['serviced']}
                # Reading six duty registers while the Guest RUNS is a
                # sampled observer, not a coherent PWM timeline or gate proof.
                try:
                    obs = observe_original_pwm(qtest.read,gate_active_level=1)
                    record['pwm_observer_ready_sample'] = obs.acceptable_for_plant
                    record['pwm_six_high_ticks_sample'] = list(obs.six_high_ticks)
                    record['pwm_period_ticks_sample'] = obs.period_ticks
                except (ValueError, AssertionError, RuntimeError) as exc:
                    record['pwm_observer_diagnostic'] = str(exc)
                evidence['telemetry'].append(record)
            time.sleep(args.autonomous_poll_ms / 1000.0)
    finally:
        # GDB 'c' is in another thread waiting for its async stop packet.
        # The sole host-initiated halt is at completion/fault/timeout,
        # never on every original 1kHz/16kHz WFI.
        if thread.is_alive():
            rsp.sock.sendall(b'\x03')
        thread.join(timeout=10)
        rsp.sock.settimeout(rsp_timeout)
    if thread.is_alive():
        raise TimeoutError('GDB did not halt after autonomous observation')
    if 'exception' in outcome:
        raise RuntimeError('Guest GDB continue exception: '+outcome['exception'])
    if not outcome.get('stop','').startswith(('S02','T02','S05','T05')):
        raise RuntimeError('Unexpected original guest GDB stop: '+str(outcome))
    core = observer(rsp)
    if core['pc'] == hardfault or core['cfsr'] or core['hfsr']:
        raise AssertionError('Original Guest fault during continuous auto SITL: '+str(core))
    after = guest_snapshot(rsp.mem32,addresses)
    status, issues = native_end_oracle(
        snap, baseline, after, scenario, max_frames=args.max_frames)
    evidence['autonomous'].update(
        final_engine=snap,
        after_guest=after,
        guest_core=core,
        host_wall_elapsed_s=time.monotonic()-started,
        native_oracle_issues=issues)
    # Native total counters are observed, but no fake per-stage Guest CRC
    # claim is made from asynchronously sampled intervals.
    remaining = snap['sent']
    for row, source in zip(evidence['stages'], scenario.stages):
        budget = (source.end_ns-source.start_ns) // 1_000_000
        row['frames_sent'] = min(budget, remaining)
        remaining -= row['frames_sent']
        row['status'] = 'OPEN_AUTONOMOUS_STAGE_GUEST_ACCEPTANCE_NOT_PROVED'
    evidence['autonomous']['valid_crc_feed_delta'] = (
        after['valid_frame_feeds']-baseline['valid_frame_feeds'])
    evidence['autonomous']['valid_crc_feed_per_sent_ratio'] = (
        (after['valid_frame_feeds']-baseline['valid_frame_feeds'])/snap['sent']
        if snap['sent'] else None)
    # Guest executes its original WFI instructions without host breakpoints;
    # number of Guest WFIs is deliberately NOT measured in this mode.
    evidence['native_wfi_visits'] = None
    evidence['autonomous']['host_runtime_wfi_breakpoint_stops'] = 0
    evidence['autonomous']['guest_wfi_count'] = 'NOT_MEASURED'
    evidence['native_guest_executed'] = True
    evidence['dshot_frames_sent'] = snap['sent']
    evidence['last_guest_virtual_elapsed_ns'] = snap['elapsed_ns']
    evidence['scripted_bemf_crossings_issued'] = snap['bemf_crossings']
    evidence['completed_full_duration'] = bool(
        not args.max_frames or args.max_frames == scenario.total_frames)
    # A bounded 50-frame smoke is NOT a full PASS and cannot qualify
    # per-stage Guest CRC and commutation even if its inputs all played.
    if evidence['completed_full_duration'] and not issues:
        feeds = after['valid_frame_feeds']
        neutral_proved = False
        packets = 0
        # Run source-owned neutral through its actual PA26 wire, not RAM.
        # Only 1-5 host GDB pauses during teardown, never per WFI.
        for _ in range(5):
            queue_dshot600_wire(qtest, 0, allow_zero=True,
                                reset_completed_wave=True)
            packets += 1
            stop, interrupted = continue_bounded(rsp, 40)
            state = observer(rsp)
            if state['pc'] == hardfault or state['cfsr'] or state['hfsr']:
                raise AssertionError('Original Guest fault during autonomous neutral teardown')
            guest = guest_snapshot(rsp.mem32,addresses)
            if guest['throt'] == 0 and guest['valid_frame_feeds'] > feeds:
                neutral_proved = True
                break
        evidence['autonomous']['neutral_teardown'] = {
            'qualified': neutral_proved,
            'physical_zero_packets': packets,
            'source_crc_increased': guest['valid_frame_feeds'] > feeds,
            'guest_throt_zero': guest['throt'] == 0}
        if not neutral_proved:
            issues.append('source_neutral_teardown_not_confirmed')
            status='FAIL_AUTONOMOUS_ORACLE'
    evidence['status']=status
    evidence['issues']=issues
    print('E62_AUTONOMOUS_SITL_VERDICT ' + json.dumps({
        'status':status, 'frames':snap['sent'],
        'guest_elapsed_ns':snap['elapsed_ns'],
        'original_crc_feeds_delta':
            after['valid_frame_feeds']-baseline['valid_frame_feeds'],
        'original_cap1_delta':
            after['captured_events']-baseline['captured_events'],
        'original_timg12_serviced_delta':
            after['serviced']-baseline['serviced'],
        'scripted_bemf_transitions':snap['bemf_crossings'],
        'issues':issues},sort_keys=True),flush=True)
    return status.startswith('PASS_')
