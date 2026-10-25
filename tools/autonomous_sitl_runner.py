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
    configure_auto, read_auto, read_stage_checkpoints,
    summarize_stage_samples, native_end_oracle,
    sampled_stage_regression_gate, read_timing_evidence,
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
    host_profiler = {
        'qtest_engine_poll_wall_s':0.0,
        'guest_sram_sampling_wall_s':0.0,
        'model_pwm_observer_wall_s':0.0,
        'host_poll_sleep_wall_s':0.0,
        'engine_poll_count':0,
        'guest_sample_count':0,
        'pwm_sample_count':0,
    }
    last_log_frames = 0
    last_sample_ms = -args.autonomous_telemetry_interval_ms
    snap = initial
    try:
        thread.start()
        while True:
            if time.monotonic() - started > args.autonomous_wall_timeout_s:
                raise TimeoutError('Bounded host wall-clock timeout before QEMU virtual duration completed')
            if not thread.is_alive() and 'exception' in outcome:
                raise RuntimeError('Original Guest RSP continue failed: '+outcome['exception'])
            stamp = time.monotonic()
            snap = read_auto(qtest.read)
            host_profiler['qtest_engine_poll_wall_s'] += time.monotonic()-stamp
            host_profiler['engine_poll_count'] += 1
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
            if (snap['elapsed_ms'] >=
                    last_sample_ms + args.autonomous_telemetry_interval_ms):
                last_sample_ms = snap['elapsed_ms']
                stamp = time.monotonic()
                g = guest_snapshot(qtest.read, addresses)
                host_profiler['guest_sram_sampling_wall_s'] += (
                    time.monotonic()-stamp)
                host_profiler['guest_sample_count'] += 1
                frame_index = min(max(snap['sent'] - 1, 0),
                                  scenario.total_frames - 1)
                intended = scenario.frame(frame_index)
                record = {'sim_elapsed_ms':snap['elapsed_ms'],
                          'stage_index':intended.stage_index,
                          'last_sent_frame_index':frame_index,
                          'intended_command_pct':float(intended.pct),
                          'intended_command_dshot':intended.dshot_value,
                          'sim_dshot_value':snap['last_dshot'],
                          'guest_throt_sample':g['throt'],
                          'guest_throttle_minus_command':
                              g['throt'] - intended.dshot_value,
                          'guest_valid_crc_feed_total':g['valid_frame_feeds'],
                          'guest_step_sample':g['step'],
                          'guest_cap1_total':g['captured_events'],
                          'guest_timg12_scheduled_total':g['scheduled'],
                          'guest_timg12_serviced_total':g['serviced']}
                # Reading six duty registers while the Guest RUNS is a
                # sampled observer, not a coherent PWM timeline or gate proof.
                stamp = time.monotonic()
                host_profiler['pwm_sample_count'] += 1
                try:
                    obs = observe_original_pwm(qtest.read,gate_active_level=1)
                    record['pwm_observer_ready_sample'] = obs.acceptable_for_plant
                    record['pwm_six_high_ticks_sample'] = list(obs.six_high_ticks)
                    record['pwm_period_ticks_sample'] = obs.period_ticks
                    record['pwm_high_tick_ratios_sample'] = (
                        [round(t/obs.period_ticks,5)
                         for t in obs.six_high_ticks]
                        if obs.period_ticks > 0 and
                        obs.acceptable_for_plant else None)
                except (ValueError, AssertionError, RuntimeError) as exc:
                    record['pwm_observer_diagnostic'] = str(exc)
                finally:
                    host_profiler['model_pwm_observer_wall_s'] += (
                        time.monotonic()-stamp)
                evidence['telemetry'].append(record)
            stamp = time.monotonic()
            time.sleep(args.autonomous_poll_ms / 1000.0)
            host_profiler['host_poll_sleep_wall_s'] += time.monotonic()-stamp
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
    continuous_run_elapsed_s = time.monotonic()-started
    evidence['autonomous']['host_perf_profile'] = {
        **host_profiler,
        'continuous_runtime_wall_s':continuous_run_elapsed_s,
        'qemu_virtual_s':snap['elapsed_ns']/1_000_000_000,
        'guest_counters_are_not_cpu_time_profiles':True,
        'unattributed_wall_s':max(0.0,
            continuous_run_elapsed_s-
            host_profiler['qtest_engine_poll_wall_s']-
            host_profiler['guest_sram_sampling_wall_s']-
            host_profiler['model_pwm_observer_wall_s']-
            host_profiler['host_poll_sleep_wall_s']),
    }
    status, issues = native_end_oracle(
        snap, baseline, after, scenario, max_frames=args.max_frames)
    evidence['autonomous'].update(
        final_engine=snap,
        after_guest=after,
        guest_core=core,
        host_wall_elapsed_s=time.monotonic()-started,
        native_oracle_issues=issues)
    # Each virtual stage boundary is latched by QEMU's input timer.
    # These are exact physical fixture counters, distinct from sampled
    # Guest CRC/throttle and modeled PWM (not coherent Guest snapshots).
    checkpoints = read_stage_checkpoints(
        qtest, scenario, max_frames=args.max_frames)
    # Collect QEMU input/CAP1/TIMG12 *hardware-event* timing while the
    # original Guest is halted. These are not Guest ISR entry timestamps.
    trace = read_timing_evidence(qtest.read)
    evidence['autonomous']['event_timing_evidence'] = trace
    evidence['autonomous']['simulator_workload_profile'] = {
        'dshot_frames':snap['sent'],
        'pa26_edge_events_delta':
            snap['pa26_capture']-baseline['pa26_capture'],
        'dma_beat_delta':snap['pa26_dma']-baseline['pa26_dma'],
        'bemf_timer_callbacks':snap['bemf_timer_callbacks'],
        'feedback_timer_mods':trace['feedback_timer_mods'],
        'route_change_notifications':trace['effective_route_changes'],
        'route_coalesced':trace['coalesced_route_changes'],
        'route_duplicate_skips':trace['duplicate_route_skips'],
        'analog_vector_commits':trace['vector_commits'],
        'analog_vector_noop_skips':trace['vector_skipped'],
        'cap1_events':trace['trace_cap1_events'],
        'timg12_irq_events':trace['trace_timg12_irq_events'],
        'units':'EVENT_COUNT_NOT_CPU_TIME',
    }
    async_stage = summarize_stage_samples(scenario, evidence['telemetry'])
    evidence['autonomous']['stage_physical_checkpoints'] = checkpoints
    evidence['autonomous']['stage_guest_async_samples'] = async_stage
    prev_sent = 0
    for row, stage_cp, stage_diag in zip(
            evidence['stages'], checkpoints, async_stage):
        if stage_cp['valid']:
            row['frames_sent'] = stage_cp['end_sent_cumulative'] - prev_sent
            prev_sent = stage_cp['end_sent_cumulative']
        else:
            row['frames_sent'] = 0
        row['physical_stage_checkpoint'] = stage_cp
        row['guest_asynchronous_stage_diagnostics'] = stage_diag
        # Old per-WFI fields are NOT filled in autonomous mode. Leaving
        # zeros/False here causes contradictory PASS+False JSON evidence.
        for legacy in ('valid_crc_feeds_observed',
                       'guest_pwm_powered_observed',
                       'guest_nonzero_throttle_observed',
                       'guest_neutral_throttle_observed',
                       'original_cap1_count_delta',
                       'original_timg12_service_delta',
                       'native_steps_observed'):
            row[legacy] = None
        row['legacy_guest_stage_fields_scope'] = (
            'NOT_MEASURED_IN_AUTONOMOUS_MODE_USE_SAMPLED_STAGE_GATE')
        row['status'] = 'OPEN_AUTONOMOUS_STAGE_GUEST_ACCEPTANCE_NOT_PROVED'
    if prev_sent != snap['sent']:
        issues.append('stage_latched_frame_total_mismatch')
    full_duration = (not args.max_frames or
                     args.max_frames == scenario.total_frames)
    if full_duration and any(not row['valid'] or not row['complete']
                             for row in checkpoints):
        issues.append('stage_physical_checkpoint_missing')
    if full_duration and any(
            cp['end_sent_cumulative'] != stage.end_ns//1_000_000
            for cp, stage in zip(checkpoints, scenario.stages)):
        issues.append('stage_sent_boundary_mismatch')
    # Additional sampled stage-gate: no guest ISR causality or all-frame
    # acceptance inferred from sparse non-coherent QTest SRAM samples.
    evidence['autonomous']['stage_gate_scope'] = (
        'REL17_3_SAMPLED_GUEST_THROTTLE_CRC_PWM_CAP1_TIMG12')
    if full_duration:
        stage_gate, stage_issues = sampled_stage_regression_gate(
            scenario, checkpoints, evidence['telemetry'])
        evidence['autonomous']['sampled_stage_regression'] = stage_gate
        for row, sample_gate in zip(evidence['stages'], stage_gate):
            row['sampled_stage_gate'] = sample_gate
            row['status'] = sample_gate['status']
        issues.extend(stage_issues)
        if (trace['trace_cap1_events'] == 0 or
            trace['trace_timg12_irq_events'] == 0 or
            trace['trace_triplets'] == 0):
            issues.append('no_qemu_temporal_cross_cap_timg12_chain')
        if (trace['feedback_timer_mods'] == 0 or
            trace['trace_cross_cap_pairs'] == 0):
            issues.append('missing_qemu_feedback_timing_observation')
        if trace['trace_cross_cap_pairs'] < 0.90*snap['bemf_crossings']:
            issues.append('temporal_cross_cap_pair_ratio_below_90_percent')
        if trace['trace_triplets'] < 0.90*trace['trace_cap1_events']:
            issues.append('temporal_pair_chain_ratio_below_90_percent')
    else:
        evidence['autonomous']['sampled_stage_regression'] = (
            'OPEN_BOUNDED_SMOKE_NOT_QUALIFIED')
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
    evidence['completed_full_duration'] = full_duration
    if issues and status.startswith('PASS_'):
        status = 'FAIL_AUTONOMOUS_ORACLE'
    # A bounded 50-frame smoke is NOT a full PASS and cannot qualify
    # per-stage Guest CRC and commutation even if its inputs all played.
    if evidence['completed_full_duration']:
        # Source-owned Neutral teardown must run even when the stage
        # regression fails, so safety/neutral evidence is not skipped.
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
        'bemf_timer_callbacks':snap.get('bemf_timer_callbacks'),
        'route_reschedules':snap.get('route_reschedules'),
        'timer_mods':trace['feedback_timer_mods'],
        'coalesced':trace['coalesced_route_changes'],
        'temporal_triplets':trace['trace_triplets'],
        'sampled_stage_gate':(
            [row['status'] for row in stage_gate]
            if full_duration else ['OPEN_BOUNDED_SMOKE']),
        'stage_checkpoints':[
            {'index':cp['index'],'sent':cp['end_sent_cumulative'],
             'complete':cp['complete']} for cp in checkpoints],
        'workload':evidence['autonomous']['simulator_workload_profile'],
        'issues':issues},sort_keys=True),flush=True)
    return status.startswith('PASS_')
