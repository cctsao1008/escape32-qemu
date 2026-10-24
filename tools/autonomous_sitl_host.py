#!/usr/bin/env python3
"""Opt-in G13B5 QEMU-autonomous scenario MMIO ABI adapter.

Only programs simulator-side input staging; never alters Guest SRAM,
native timers, PWM/ECAP/IRQ registers, or Firmware throttle.
"""
from decimal import Decimal
from tools.functional_dshot_scenario import ScenarioError, percent_to_dshot

AUTO_BASE = 0x5ffea000
AUTO_MAGIC = 0x41323645
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
        raise RuntimeError('Custom QEMU lacks G13B5 autonomous SITL port; rebuild ./build.sh')
    names = ('status','sent','target_frames','last_dshot','bemf_crossings',
             'elapsed_ms','error','analog_updates','pwm_samples',
             'stage','pa26_capture','pa26_dma')
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
        raise RuntimeError('G13B5 QEMU fixture absent: rebuild QEMU')
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
