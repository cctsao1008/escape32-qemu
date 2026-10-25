"""Rel17.3 strict *sampled* Guest Stage regression oracle.

This verifies bounded asynchronous samples, not each wire DShot frame.
"""
from tools.sitl_autonomous_transport import FRAME_NS

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
        # Hardware-visible comparator mux+polarity observations are
        # latched by QEMU at each stage boundary, independent of sparse
        # Guest reads. A steady positive hold must visit all six states.
        phase_mask = cp.get('phase_polarity_mask')
        transitions = cp.get('phase_polarity_transitions')
        if (stage.kind != 'ramp' and stage.to_pct > 0 and
            stage_ms >= 1000 and
            (phase_mask != 0x3f or transitions is None or transitions < 6)):
            local.append('six_phase_polarity_states_not_observed')
        errors = []
        steady_errors = []
        transition_grace_ms = 500 if (stage.kind == 'hold' and
            stage.index > 0 and scenario.stages[stage.index-1].to_pct != stage.to_pct) else 0
        settled = []
        for r in group:
            cmd = r['intended_command_dshot']
            expected = cmd - 47 if cmd else 0
            error = abs(r['guest_throt_sample'] - expected)
            errors.append(error)
            if r['sim_elapsed_ms']-start_ms >= transition_grace_ms:
                steady_errors.append(error)
                settled.append(r)
            if r['sim_dshot_value'] != cmd:
                local.append('wire_command_not_as_intended')
        # Async sampling at Stage boundary may see the prior 1kHz wire
        # frame: require settling within 500ms and strict thereafter.
        # The new source-owned stage still must make real CRC progress.
        if not settled and group:
            local.append('no_post_transition_guest_sample')
        if steady_errors and max(steady_errors) > tolerance:
            local.append('guest_throttle_out_of_tolerance')
        if stage.kind == 'hold' and stage.to_pct == 0:
            for r in settled:
                if r['guest_throt_sample'] != 0:
                    local.append('neutral_stage_guest_throttle_not_zero')
                # Ready+nonzero differential PWM in sustained neutral
                # is a safety-significant unexpected powered output.
                if r.get('pwm_observer_ready_sample'):
                    ticks = r.get('pwm_six_high_ticks_sample')
                    if isinstance(ticks,(tuple,list)) and len(ticks)==6:
                        if any(ticks[2*i]!=ticks[2*i+1] for i in range(3)):
                            local.append('neutral_stage_powered_pwm')
        crc = [r['guest_valid_crc_feed_total'] for r in group]
        if len(crc) >= 2 and (
            crc[-1] <= crc[0] or
            any(b < a for a,b in zip(crc, crc[1:]))
        ):
            local.append('guest_crc_not_progressing')
        # Source counter delta is measured over the VIRTUAL sample span;
        # not inferred to mean every transmitted packet was decoded.
        sampled_span = (group[-1]['sim_elapsed_ms'] -
                        group[0]['sim_elapsed_ms']) if len(group)>1 else 0
        sampled_feed_ratio = ((crc[-1]-crc[0]) / sampled_span
                              if sampled_span>0 else None)
        if (sampled_feed_ratio is not None and
            sampled_feed_ratio < 0.90):
            local.append('sampled_crc_feed_ratio_below_90_percent')
        if stage.to_pct > 0 and len(group) >= 2:
            ready_count = 0
            for r in group:
                if not r.get('pwm_observer_ready_sample'):
                    continue
                ticks = r.get('pwm_six_high_ticks_sample')
                period = r.get('pwm_period_ticks_sample')
                if (not isinstance(ticks,(tuple,list)) or len(ticks)!=6
                        or not isinstance(period,int) or period<=0):
                    continue
                if any(not 0<=t<=period for t in ticks):
                    local.append('pwm_tick_out_of_range')
                    continue
                if any(ticks[i]+ticks[i+1]>period
                       for i in (0,2,4)):
                    local.append('pwm_phase_overlap')
                    continue
                if not any(ticks[i]!=ticks[i+1] for i in (0,2,4)):
                    local.append('pwm_no_differential_phase_drive')
                    continue
                ready_count+=1
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
            'max_settled_throttle_error':(
                max(steady_errors) if steady_errors else None),
            'post_transition_samples':len(settled),
            'transition_grace_ms':transition_grace_ms,
            'neutral_powered_pwm_scope':'READ_ONLY_ASYNC_DIFFERENTIAL_OUTPUT',
            'crc_delta_between_samples':(
                crc[-1]-crc[0] if len(crc)>1 else None),
            'sampled_crc_feed_ratio':sampled_feed_ratio,
            'observed_phase_polarity_mask':phase_mask,
            'observed_phase_polarity_transitions':transitions,
            'issues':local,
            'scope':'REL17_3_ASYNC_GUEST_SAMPLES_NOT_EVERY_FRAME',
        })
        issues.extend(f'stage_{stage.index}:{reason}' for reason in local)
    if len(checkpoints) != len(scenario.stages):
        issues.append('checkpoint_count_mismatch')
    return results, issues
