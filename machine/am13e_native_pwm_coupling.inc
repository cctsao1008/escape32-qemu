static bool am13e_native_motor_gate_ok(AM13ESimPWM *p)
{
    uint32_t gate = am13e_pwm4_hist_gate_word(p);
    return (gate & 15U) == 15U && p->running &&
           (p->reg[0xb0U/4U] & 0x60000U) == 0U;
}
/* Invoked by native QEMU AQ/DB clock callback or Guest PWM MMIO/Trip
 * event: advance OLD switching state up to this virtual timestamp;
 * immediately latch NEW mask. No ring polling or host control. */
static void am13e_native_motor_pwm_event(AM13ESimPWM *p,
                                         uint32_t newmask, bool valid)
{
    AM13ENativeMotor *m = &p->machine->native_motor;
    if (!m->enabled || m->faulted) {
        return;
    }
    bool gate = am13e_native_motor_gate_ok(p);
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    if (m->active && !am13e_native_motor_advance(m, now)) {
        am13e_native_motor_fault(m, 1U);
        return;
    }
    if (gate && !valid) {
        am13e_native_motor_fault(m, 2U);
        return; /* Never accept an invalid source-level evaluator. */
    }
    for (int k = 0; k < 3; k++) {
        if ((newmask & (3U << (2*k))) == (3U << (2*k)) && gate) {
            am13e_native_motor_fault(m, 5U); /* G14 same-leg overlap */
            return;
        }
    }
    if (!m->active && gate && valid && newmask) {
        m->active = true;
        m->last_ns = now;
        timer_mod(m->tick_timer, now+AM13E_NATIVE_MOTOR_STEP_NS);
    }
    if (m->active) {
        bool p0_recorded_switch = false;
        double switch_current_before[3] = {
            m->currents[0],m->currents[1],m->currents[2]
        };
        /* Log only six-step *power-pair changes*, not every 16kHz
         * PWM carrier edge. No made-up commutation from duty ratios. */
        if (gate && valid) {
            unsigned hi=0U,lo=0U,hi_phase=0U,lo_phase=0U;
            for(unsigned k=0;k<3U;++k) {
                if(newmask & (1U<<(2*k))) { ++hi; hi_phase=k; }
                if(newmask & (1U<<(2*k+1))) { ++lo; lo_phase=k; }
            }
            if(hi==1U && lo==1U && hi_phase!=lo_phase) {
                uint32_t pair=1U+hi_phase*3U+lo_phase;
                if(pair!=m->p0_last_pair) {
                    m->p0_last_pair=pair;
                    am13e_p0_event(p->machine,"PWM_PAIR",pair,
                                   newmask,am13e_pwm4_hist_gate_word(p),
                                   (int64_t)llround(m->theta_unwrapped*1000.0),
                                   p->zero_events,0);
                }
            }
        }
        if(m->p0_first_switch_ns < 0 && gate && valid && newmask) {
            m->p0_first_switch_ns = now;
        }
        if(m->p0_first_switch_ns >= 0 &&
           now-m->p0_first_switch_ns <= INT64_C(120000000) &&
           (newmask != m->p0_last_logged_mask ||
            (gate && valid) != m->p0_last_logged_gate)) {
            /* Full *bounded* 120ms real-clocked six-pad switching source
             * for independent current-step replay. NO host motor drive. */
            am13e_p0_event(p->machine,"SWITCH",newmask & 0x3fU,
                           gate && valid,am13e_pwm4_hist_gate_word(p),
                           m->energy_steps,0,0);
            m->p0_last_logged_mask=newmask;
            m->p0_last_logged_gate=gate && valid;
            p0_recorded_switch = true;
        }
        /* Optional, bounded, independent post-neutral SWITCH evidence.
         * Same original AQ/DB callback, same clock and mask; records only
         * transitions. Default OFF. No extrapolated carrier edges, no
         * motor-state writes, no Guest MMIO, no effect on P0 strict SWITCH
         * records. Separate event kind prevents accidental P0 gate reuse. */
        if (m->source_focus_end_ns > m->source_focus_begin_ns &&
            now >= m->source_focus_begin_ns &&
            now <= m->source_focus_end_ns &&
            (newmask != m->source_focus_last_logged_mask ||
             (gate && valid) != m->source_focus_last_logged_gate)) {
            if (m->source_focus_record_count < 12000U) {
                am13e_p0_event(p->machine, "SWITCH_FOCUS",
                               newmask & 0x3fU, gate && valid,
                               am13e_pwm4_hist_gate_word(p),
                               m->energy_steps, p->zero_events,
                               m->switch_events);
                ++m->source_focus_record_count;
                m->source_focus_last_logged_mask = newmask;
                m->source_focus_last_logged_gate = gate && valid;
            } else if (!m->source_focus_budget_hit) {
                am13e_p0_event(p->machine, "SWITCH_FOCUS_LIMIT",
                               m->source_focus_record_count, 12000,
                               0, 0, 0, 0);
                m->source_focus_budget_hit = true;
            }
        }
        /* Tie analog switching artifact to ACTUAL MCPWM AQ/DB transitions,
         * not to a guessed carrier frequency or synthetic ECAP event. */
        if (gate && valid && newmask != m->mask &&
            m->bemf_stress_switch_code) {
            m->bemf_stress_last_switch_ns=now;
            ++m->bemf_stress_switch_edges;
        }
        m->mask = newmask & 0x3fU;
        m->gate = gate && valid;
        if (p0_recorded_switch) {
            /* A pure switch event has zero elapsed physical time:
             * changing topology MUST NOT discard stored inductor
             * current. Emit before/after phase currents at identical
             * virtual time for the independent P0 audit. */
            if (memcmp(switch_current_before,m->currents,
                       sizeof(switch_current_before)) != 0) {
                am13e_native_motor_fault(m, 7U);
                return;
            }
            am13e_p0_event(p->machine,"SWITCH_CURRENT",
                           (int64_t)llround(switch_current_before[0]*1000),
                           (int64_t)llround(switch_current_before[1]*1000),
                           (int64_t)llround(switch_current_before[2]*1000),
                           (int64_t)llround(m->currents[0]*1000),
                           (int64_t)llround(m->currents[1]*1000),
                           (int64_t)llround(m->currents[2]*1000));
        }
        ++m->switch_events;
        am13e_native_motor_publish(m);
        if (!m->faulted) {
            am13e_native_motor_publish_oc(m);
        }
    }
}
