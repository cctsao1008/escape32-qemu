#!/usr/bin/env python3
"""Stable QEMU-autonomous simulator-only MMIO/Scenario adapter.

Only programs simulator-side input staging; never alters Guest SRAM,
native timers, PWM/ECAP/IRQ registers, or Firmware throttle.
"""
from decimal import Decimal
from tools.functional_dshot_scenario import ScenarioError, percent_to_dshot

AUTO_BASE = 0x5ffea000
AUTO_MAGIC = 0x41323645
AUTO_ABI = 4  # G13B7.1 atomically committed phases and stage observer
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
    'stage_phase_mask': 0x100, 'stage_phase_transitions': 0x104,
    'vector_skipped': 0x108, 'vector_commits': 0x10c,
    'live_phase_mask': 0x110, 'live_phase_transitions': 0x114,
    'schema_magic': 0x118,
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
             'bemf_timer_callbacks','route_reschedules',
             'vector_skipped','vector_commits')
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
        raise RuntimeError('G13B7.1 atomic feedback ABI missing: rebuild QEMU')
    if qtest.read(AUTO_BASE+REG['schema_magic']) != 0x53363134:
        raise RuntimeError('G13B7.1 stage observer schema missing')
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
    accepted = after['valid_frame_feeds'] - before['valid_frame_feeds']
    if accepted <= 0:
        reasons.append('no_original_crc_acceptance')
    # Regression threshold, not a wire BER/acceptance guarantee. The
    # existing G13B5/B6/B7 11s baselines are ~0.96.
    if not (max_frames and target < scenario.total_frames):
        if accepted < target * 0.90:
            reasons.append('aggregate_crc_feed_ratio_below_90_percent')
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
            'phase_polarity_mask':r('stage_phase_mask'),
            'phase_polarity_transitions':r('stage_phase_transitions'),
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


