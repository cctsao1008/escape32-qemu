"""Stage diagnostics and time-correlation evidence (read-only)."""
from tools.sitl_autonomous_transport import (
    AUTO_BASE, AUTO_MAGIC, AUTO_ABI, REG, FRAME_NS,
)

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
    values['vector_skipped'] = read('vector_skipped')
    values['vector_commits'] = read('vector_commits')
    values['scope'] = (
        'QEMU_VIRTUAL_TIME_ADJACENT_EVENTS_NOT_GUEST_ISR_PROOF')
    values['pairing_window_ns'] = 3_000_000
    return values


