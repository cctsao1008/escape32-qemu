#!/usr/bin/env python3
"""Opt-in G13B5 QEMU-autonomous scenario MMIO ABI adapter.

Only programs simulator-side input staging; never alters Guest SRAM,
native timers, PWM/ECAP/IRQ registers, or Firmware throttle.
"""
from decimal import Decimal
from tools.functional_dshot_scenario import ScenarioError, percent_to_dshot

AUTO_BASE = 0x5ffea000
AUTO_MAGIC = 0x41323645
AUTO_ABI = 3  # G13B7 timer coalescing and event timing
AUTO_RUNNING, AUTO_DONE, AUTO_ERROR = 1, 2, 4
FRAME_NS = 1_000_000
REG = {
    'magic': 0x00, 'command': 0x04, 'status': 0x08,
    'stage_count': 0x0c, 'stage_index': 0x10,
    'duration_ms': 0x14, 'start_permille': 0x18,
    'end_permille': 0x1c, 'update_ms': 0x20,
    'max_frames': 0x24, 'sent': 0x28, 'target_frames': 0x2c,
    'last_dshot': 0x30, 'bemf_crossings': 0x34,
    'elapsed_ms': 0x38, 'error': 0x3c,
    'elapsed_ns_lo': 0x40, 'elapsed_ns_hi': 0x44,
    'analog_updates': 0x48, 'pwm_samples': 0x4c,
    'stage': 0x50, 'pa26_capture': 0x54, 'pa26_dma': 0x58,
    'stage_query': 0x5c, 'stage_end_sent': 0x60,
    'stage_end_capture': 0x64, 'stage_end_dma': 0x68,
    'stage_end_crossings': 0x6c, 'stage_status': 0x70,
    'stage_end_ms': 0x74, 'stage_end_bemf_callbacks': 0x78,
    'stage_end_analog_updates': 0x7c,
    'bemf_timer_callbacks': 0x80, 'route_reschedules': 0x84,
    'abi_version': 0x88,
    'effective_route_changes': 0x8c, 'coalesced_route_changes': 0x90,
    'feedback_timer_mods': 0x94, 'duplicate_route_skips': 0x98,
    'trace_cap1_events': 0x9c, 'trace_timg12_irq_events': 0xa0,
    'trace_cross_cap_pairs': 0xa4, 'trace_cap_timg12_pairs': 0xa8,
    'trace_triplets': 0xac, 'trace_cross_cap_last_ns': 0xb0,
    'trace_cap_timg12_last_ns': 0xb4,
    'trace_cross_cap_max_ns': 0xb8, 'trace_cap_timg12_max_ns': 0xbc,
    'trace_cross_cap_min_ns': 0xc0, 'trace_cap_timg12_min_ns': 0xc4,
    'trace_cross_cap_sum_lo': 0xc8, 'trace_cross_cap_sum_hi': 0xcc,
    'trace_cap_timg12_sum_lo': 0xd0, 'trace_cap_timg12_sum_hi': 0xd4,
    'trace_unpaired_cap1': 0xd8, 'trace_unpaired_timg12': 0xdc,
    'trace_overwritten_crossings': 0xe0, 'trace_overwritten_cap1': 0xe4,
    'trace_last_cross_lo': 0xe8, 'trace_last_cross_hi': 0xec,
    'trace_last_cap1_lo': 0xf0, 'trace_last_cap1_hi': 0xf4,
    'trace_last_timg12_lo': 0xf8, 'trace_last_timg12_hi': 0xfc,
}


def _millis(ns):
    if type(ns) is not int or ns <= 0 or ns % FRAME_NS:
        raise ScenarioError('Autonomous stage requires whole positive milliseconds')
    return ns // FRAME_NS


def _permille(percent):
    value = Decimal(str(percent))*10
    if value != value.to_integral_value() or not 0 <= value <= 1000:
        raise ScenarioError('Autonomous stage percentages require exact 0.1%')
    return int(value)


def compile_autonomous_stages(scenario):
    if scenario.frame_period_ns != FRAME_NS:
        raise ScenarioError('Autonomous QEMU only supports 1kHz physical DShot')
    if not 1 <= len(scenario.stages) <= 16:
        raise ScenarioError('Autonomous QEMU requires 1..16 stages')
    records = []
    for s in scenario.stages:
        duration = _millis(s.end_ns-s.start_ns)
        update = _millis(s.update_ns)
        start = _permille(s.from_pct)
        end = _permille(s.to_pct)
        if duration > 120000 or duration % update or (abs(end-start)*update)%duration:
            raise ScenarioError('Autonomous stage interpolation not representable')
        records.append(dict(duration_ms=duration, start_permille=start,
                            end_permille=end, update_ms=update))
    if sum(x['duration_ms'] for x in records) != scenario.total_frames:
        raise ScenarioError('Autonomous stage length differs from scenario')
    return records


def read_auto(read32):
    def get(k): return read32(AUTO_BASE+REG[k])
    if get('magic') != AUTO_MAGIC:
        raise RuntimeError('Custom QEMU lacks autonomous SITL port; rebuild ./build.sh')
    abi = get('abi_version')
    if abi != AUTO_ABI:
        raise RuntimeError(f'G13B7 needs autonomous ABI {AUTO_ABI}; QEMU returned {abi}. Rebuild ./build.sh')
    names = ('status','sent','target_frames','last_dshot','bemf_crossings',
             'elapsed_ms','error','analog_updates','pwm_samples',
             'stage','pa26_capture','pa26_dma',
             'bemf_timer_callbacks','route_reschedules')
    values = {k:get(k) for k in names}
    values['elapsed_ns'] = get('elapsed_ns_lo') | (get('elapsed_ns_hi') << 32)
    return values


def configure_auto(qtest, scenario, *, max_frames=0):
    stages = compile_autonomous_stages(scenario)
    if type(max_frames) is not int or not 0 <= max_frames <= scenario.total_frames:
        raise ScenarioError('Invalid autonomous frame bound')
    def put(k,v):
        qtest.write(AUTO_BASE+REG[k],v)
    if qtest.read(AUTO_BASE+REG['magic']) != AUTO_MAGIC:
        raise RuntimeError('Autonomous QEMU fixture absent: rebuild QEMU')
    if qtest.read(AUTO_BASE+REG['abi_version']) != AUTO_ABI:
        raise RuntimeError('G13B7 temporal-evidence ABI missing: rebuild QEMU')
    put('command',3)  # clear simulator fixture only, never Guest RAM
    put('stage_count',len(stages))
    for i,stage in enumerate(stages):
        put('stage_index',i)
        for key in ('duration_ms','start_permille','end_permille','update_ms'):
            put(key,stage[key])
            if qtest.read(AUTO_BASE+REG[key]) != stage[key]:
                raise AssertionError('Autonomous stage readback mismatch: '+key)
    put('max_frames',max_frames)
    put('command',1)
    snapshot = read_auto(qtest.read)
    if not (snapshot['status'] & AUTO_RUNNING):
        raise AssertionError('Autonomous QEMU did not arm valid stages')
    if snapshot['target_frames'] != (max_frames or scenario.total_frames):
        raise AssertionError('Autonomous expected frame count mismatch')
    return snapshot


def native_end_oracle(snapshot, before, after, scenario, *, max_frames=0):
    """Conservative aggregate native check; stage-by-stage CRC not claimed."""
    target = max_frames or scenario.total_frames
    reasons = []
    if snapshot['error'] or snapshot['status'] != AUTO_DONE:
        reasons.append('engine_not_cleanly_done')
    if snapshot['sent'] != target or snapshot['target_frames'] != target:
        reasons.append('transmitted_frame_count')
    # QEMU's timer expiry may be dispatched on a later icount boundary.
    # Preserve actual elapsed virtual ns; never claim an exact deadline
    # when the guest-clock callback was serviced a few ticks late.
    if not target * FRAME_NS <= snapshot['elapsed_ns'] <= target * FRAME_NS + 100_000:
        reasons.append('virtual_time_duration_outside_100us_bound')
    if snapshot['pa26_capture'] <= before['pa26_capture'] or (
            snapshot['pa26_dma'] <= before['pa26_dma']):
        reasons.append('no_physical_pa26_dma')
    if after['valid_frame_feeds'] <= before['valid_frame_feeds']:
        reasons.append('no_original_crc_acceptance')
    if scenario.stages[-1].to_pct > 0 and after['throt'] <= 1:
        reasons.append('original_guest_final_throttle_not_positive')
    if max_frames and target < scenario.total_frames:
        return 'OPEN_AUTONOMOUS_BOUNDED_SMOKE', reasons
    if (snapshot['pwm_samples'] == 0 or snapshot['bemf_crossings'] == 0 or
            after['captured_events'] <= before['captured_events'] or
            after['serviced'] <= before['serviced']):
        reasons.append('no_original_pwm_cap1_timg12')
    return ('PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL'
            if not reasons else 'FAIL_AUTONOMOUS_ORACLE'), reasons


def read_stage_checkpoints(qtest, scenario, *, max_frames=0):
    """Return QEMU-latched PHYSICAL stage totals at exact virtual boundaries.

    Stage-select is a simulator diagnostic bank switch, never Guest MMIO.
    This contains no Guest SRAM CRC/throttle and does not assert a Stage PASS.
    Call while the Guest has been stopped after the scenario.
    """
    read = qtest.read
    write = qtest.write
    if read(AUTO_BASE + REG['abi_version']) != AUTO_ABI:
        raise RuntimeError('Stage observer ABI mismatch')
    rows = []
    start_sent = start_capture = start_dma = start_crossings = 0
    # Initial capture / DMA counts include source ARM frames; per-stage
    # deltas are computed relative to first stage snapshot predecessor
    # by the adapter using baseline values.
    for i,stage in enumerate(scenario.stages):
        write(AUTO_BASE + REG['stage_query'],i)
        if read(AUTO_BASE + REG['stage_query']) != i:
            raise AssertionError('Stage selection readback mismatch')
        r = lambda key: read(AUTO_BASE+REG[key])
        flags = r('stage_status')
        info = {
            'index': i, 'valid': bool(flags & 1),
            'complete': bool(flags & 2),
            'end_sent_cumulative': r('stage_end_sent'),
            'end_capture_cumulative': r('stage_end_capture'),
            'end_dma_cumulative': r('stage_end_dma'),
            'end_crossings_cumulative': r('stage_end_crossings'),
            'end_elapsed_ms': r('stage_end_ms'),
            'end_bemf_timer_callbacks_cumulative':
                r('stage_end_bemf_callbacks'),
            'end_analog_updates_cumulative': r('stage_end_analog_updates'),
            'declared_start_ms': stage.start_ns//FRAME_NS,
            'declared_end_ms': stage.end_ns//FRAME_NS,
        }
        if info['complete'] and not info['valid']:
            raise AssertionError('Stage marked complete without latch')
        if info['valid']:
            if info['end_sent_cumulative'] < start_sent:
                raise AssertionError('Stage cumulative sent regressed')
            if info['end_capture_cumulative'] < start_capture or (
                    info['end_dma_cumulative'] < start_dma) or (
                    info['end_crossings_cumulative'] < start_crossings):
                raise AssertionError('Stage physical counters regressed')
            start_sent = info['end_sent_cumulative']
            start_capture = info['end_capture_cumulative']
            start_dma = info['end_dma_cumulative']
            start_crossings = info['end_crossings_cumulative']
        rows.append(info)
    return rows


def summarize_stage_samples(scenario, samples):
    """Asynchronous Guest samples grouped by virtual stage, not exact latches.

    Separate Guest's reported throttle from DShot command and PWM's
    modeled six-channel duty high ticks; never conflate with real RPM.
    """
    rows = []
    for stage in scenario.stages:
        start_ms, end_ms = stage.start_ns//FRAME_NS,stage.end_ns//FRAME_NS
        group = [s for s in samples if
                 start_ms <= s['sim_elapsed_ms'] < end_ms and
                 s['sim_dshot_value'] is not None]
        values = [s['guest_throt_sample'] for s in group]
        accepted = [s['guest_valid_crc_feed_total'] for s in group]
        duty = [s['pwm_high_tick_ratios_sample']
                for s in group if s.get('pwm_high_tick_ratios_sample') is not None]
        rows.append({
            'index': stage.index, 'stage_kind':stage.kind,
            'sample_count':len(group),
            'guest_throttle_first':values[0] if values else None,
            'guest_throttle_last':values[-1] if values else None,
            'guest_throttle_min':min(values) if values else None,
            'guest_throttle_max':max(values) if values else None,
            'first_sample_ms':group[0]['sim_elapsed_ms'] if group else None,
            'last_sample_ms':group[-1]['sim_elapsed_ms'] if group else None,
            'crc_feed_delta_between_samples':
                accepted[-1]-accepted[0] if len(accepted)>1 else None,
            'last_sample_command_dshot':
                group[-1]['sim_dshot_value'] if group else None,
            'last_sample_guest_minus_command':
                values[-1]-group[-1]['sim_dshot_value'] if values else None,
            'modeled_pwm_ratio_sample_count':len(duty),
            'last_modeled_six_high_tick_ratios':duty[-1] if duty else None,
            'provenance':'ASYNC_GUEST_SRAM_AND_MODELED_PWM_DIAGNOSTIC_NOT_STAGE_ORACLE',
        })
    return rows


def read_timing_evidence(read32):
    """QEMU time-adjacent events, NOT proven Guest ISR or rotor causality."""
    def read(k):
        return read32(AUTO_BASE + REG[k])
    if read('magic') != AUTO_MAGIC or read('abi_version') != AUTO_ABI:
        raise RuntimeError('G13B7 timing ABI mismatch')
    names = (
        'effective_route_changes', 'coalesced_route_changes',
        'feedback_timer_mods', 'duplicate_route_skips',
        'trace_cap1_events', 'trace_timg12_irq_events',
        'trace_cross_cap_pairs', 'trace_cap_timg12_pairs', 'trace_triplets',
        'trace_cross_cap_last_ns', 'trace_cap_timg12_last_ns',
        'trace_cross_cap_max_ns', 'trace_cap_timg12_max_ns',
        'trace_cross_cap_min_ns', 'trace_cap_timg12_min_ns',
        'trace_unpaired_cap1', 'trace_unpaired_timg12',
        'trace_overwritten_crossings', 'trace_overwritten_cap1',
    )
    values = {k: read(k) for k in names}
    for name in ('cross_cap', 'cap_timg12'):
        values[f'trace_{name}_sum_ns'] = (
            read(f'trace_{name}_sum_lo') |
            (read(f'trace_{name}_sum_hi') << 32))
        pairs = values[f'trace_{name}_pairs']
        values[f'trace_{name}_mean_ns'] = (
            values[f'trace_{name}_sum_ns'] / pairs if pairs else None)
    for name in ('cross', 'cap1', 'timg12'):
        values[f'last_{name}_elapsed_ns'] = (
            read(f'trace_last_{name}_lo') |
            (read(f'trace_last_{name}_hi') << 32))
    values['scope'] = (
        'QEMU_VIRTUAL_TIME_ADJACENT_EVENTS_NOT_GUEST_ISR_PROOF')
    values['pairing_window_ns'] = 3_000_000
    return values


def sampled_stage_regression_gate(scenario, checkpoints, samples):
    """Rel17.3 sampled stage response oracle (not all-frame acceptance).

    A positive DShot value N corresponds to internal throttle N-47.
    The tolerance is explicitly for asynchronous 200ms observations,
    not an electrical or closed-loop control specification.
    """
    issues, results = [], []
    for stage, cp in zip(scenario.stages, checkpoints):
        start_ms = stage.start_ns // FRAME_NS
        end_ms = stage.end_ns // FRAME_NS
        stage_ms = end_ms - start_ms
        group = sorted((r for r in samples if
                        start_ms <= r['sim_elapsed_ms'] < end_ms),
                       key=lambda r:r['sim_elapsed_ms'])
        local = []
        if not cp['complete'] or not cp['valid']:
            local.append('checkpoint_missing')
        if cp['end_sent_cumulative'] != end_ms:
            local.append('stage_frame_boundary_mismatch')
        if stage.kind == 'ramp':
            tolerance, minimum = 100, 3
        else:
            tolerance, minimum = 2, 3
            if group and (
                group[-1]['sim_elapsed_ms'] -
                group[0]['sim_elapsed_ms'] < stage_ms // 2
            ):
                local.append('insufficient_hold_coverage')
        if len(group) < minimum:
            local.append('insufficient_guest_samples')
        errors = []
        for r in group:
            cmd = r['intended_command_dshot']
            expected = cmd - 47 if cmd else 0
            errors.append(abs(r['guest_throt_sample'] - expected))
            if r['sim_dshot_value'] != cmd:
                local.append('wire_command_not_as_intended')
        if errors and max(errors) > tolerance:
            local.append('guest_throttle_out_of_tolerance')
        crc = [r['guest_valid_crc_feed_total'] for r in group]
        if len(crc) >= 2 and (
            crc[-1] <= crc[0] or
            any(b < a for a,b in zip(crc, crc[1:]))
        ):
            local.append('guest_crc_not_progressing')
        if stage.to_pct > 0 and len(group) >= 2:
            ready_count = sum(bool(r.get('pwm_observer_ready_sample') and
                               r.get('pwm_high_tick_ratios_sample') is not None)
                              for r in group)
            if ready_count < 2:
                local.append('insufficient_pwm_observation')
            for key in ('guest_cap1_total','guest_timg12_serviced_total'):
                series = [r[key] for r in group]
                if series[-1] <= series[0] or any(
                    b < a for a,b in zip(series,series[1:])
                ):
                    local.append('guest_'+key+'_not_progressing')
        if stage.kind == 'ramp' and stage.to_pct > stage.from_pct and (
            len(group) >= 2 and
            group[-1]['guest_throt_sample'] <= group[0]['guest_throt_sample']
        ):
            local.append('ramp_guest_throttle_did_not_increase')
        if not group:
            local.append('no_stage_sample')
        local = list(dict.fromkeys(local))
        status = ('PASS_SAMPLED_STAGE_DIAGNOSTIC' if not local else
                  'FAIL_SAMPLED_STAGE_DIAGNOSTIC')
        results.append({
            'index':stage.index, 'kind':stage.kind, 'status':status,
            'sample_count':len(group), 'tolerance_counts':tolerance,
            'max_sampled_throttle_error':max(errors) if errors else None,
            'crc_delta_between_samples':(
                crc[-1]-crc[0] if len(crc)>1 else None),
            'issues':local,
            'scope':'REL17_3_ASYNC_GUEST_SAMPLES_NOT_EVERY_FRAME',
        })
        issues.extend(f'stage_{stage.index}:{reason}' for reason in local)
    if len(checkpoints) != len(scenario.stages):
        issues.append('checkpoint_count_mismatch')
    return results, issues
