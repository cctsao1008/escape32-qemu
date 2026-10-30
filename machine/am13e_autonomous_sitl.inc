/*
 * E62 G13B5 EXPERIMENTAL autonomous functional SITL (SIM_ONLY).
 *
 * 0x5ffea000 test port. Host configures stage durations and DShot throttle
 * BEFORE starting. QEMU virtual timers deliver every PA26 DShot600 EDGE via
 * the original G7B wave scheduler, and synthetic analogue U/V/W voltages
 * via the original G10 filtered comparator path. The unchanged Guest owns
 * GPIO capture, TIMG4, DMA, CRC, PWM, CMPSS, ECAP and TIMG12 ISR.
 *
 * This is intentionally NOT a rotor/energy/MOSFET model. No Guest SRAM,
 * peripheral control register, CAP1, IRQ or timestamp is written here.
 * The host must independently verify original Guest state.
 */
#define AM13E_AUTO_BASE UINT32_C(0x5ffea000)
#define AM13E_AUTO_SIZE 0x200U
#define AM13E_AUTO_MAGIC UINT32_C(0x41323645) /* E62A */
#define AM13E_AUTO_MAX_STAGES 16U
#define AM13E_AUTO_FRAME_NS INT64_C(1000000)
/* One-shot phase crossing at 750us, no fixed 100us analogue polling. */
#define AM13E_AUTO_ROUTE_REEVAL_NS INT64_C(100)
#define AM13E_AUTO_BEMF_CROSS_NS INT64_C(750000)
#define AM13E_AUTO_STATUS_RUNNING 1U
#define AM13E_AUTO_STATUS_DONE 2U
#define AM13E_AUTO_STATUS_ERROR 4U

/* Port registers (all LE 32-bit, SIM_ONLY):
 * +00 magic RO; +04 command WO (1 start,2 abort,3 reset idle)
 * +08 state RO; +0c stage_count RW [1..16]; +10 stage_index RW
 * +14 stage_duration_ms RW; +18 stage_start_permille RW
 * +1c stage_end_permille RW; +20 stage_update_ms RW
 * +24 max_frames RW (0 means full duration)
 * +28 transmitted_frames RO; +2c expected_frames RO
 * +30 last_dshot RO; +34 bemf_crossing_transitions RO
 * +38 elapsed_scenario_ms RO; +3c error_code RO
 * +40/44 latched virtual elapsed ns LO/HI RO
 * +48 analog_vector_updates RO; +4c powered_pwm_samples RO
 * +50 current_stage RO; +54 physical_PA26_capture RO
 * +58 physical_PA26_DMA_beat RO
 * +5c stage evidence selector RW (even after DONE, SIM_ONLY only)
 * +60 stage_end_sent RO; +64 stage_end_capture RO; +68 stage_end_dma RO
 * +6c stage_end_crossings RO; +70 stage_finished_flag RO
 * +74 stage_end_elapsed_ms RO; +78 stage_end_bemf_timer_callbacks RO
 * +7c stage_end_analog_updates RO; +80 live_bemf_timer_callbacks RO
 * +84 live_route_reschedule_count RO; +88 ABI version RO (=3)
 * +8c effective route notifications; +90 suppressed early-timer overwrites
 * +94 feedback timer_mod attempts (actual); +98 fingerprint-duplicate skips
 * +9c CAP1 event count; +a0 TIMG12 timer ZERO-IRQ event count
 * +a4 stimulus/CAP1 temporal pairs; +a8 CAP1/TIMG12 temporal pairs
 * +ac complete temporal triplets (not verified ISR causality)
 * +b0 last stimulus->CAP1 delta ns; +b4 last CAP1->T12 delta ns
 * +b8 maximum stimulus->CAP1 delta ns; +bc maximum CAP1->T12 ns
 * +c0 minimum stimulus->CAP1 ns; +c4 minimum CAP1->T12 ns
 * +c8/c c stimulus->CAP1 sum ns 64-bit; +d0/d4 CAP1->T12 sum ns
 * +d8 unpaired CAP1; +dc unpaired T12; +e0 overwritten stimulus;
 * +e4 overwritten CAP1; +e8 last stimulus virtual time ns LO;
 * +ec last stimulus virtual time ns HI; +f0 last CAP1 ns LO;
 * +f4 last CAP1 ns HI; +f8 last TIMG12 IRQ ns LO; +fc HI
 * +100 stage observed phase+polarity mask (6 bits); +104 transitions
 * +108 no-op analog evaluation skips; +10c coherent vector commits
 * +110 active-current stage phase+polarity mask; +114 stage transitions
 * +118 version 4 semantic CRC of staged observer contract
 */
static void am13e_auto_reset(AM13EAutoSITL *a)
{
    if (a->dshot_timer) {
        timer_del(a->dshot_timer);
    }
    if (a->bemf_timer) {
        timer_del(a->bemf_timer);
    }
    memset(a->stages, 0, sizeof(a->stages));
    memset(a->stage_evidence, 0, sizeof(a->stage_evidence));
    a->stage_query = a->bemf_timer_callbacks = a->route_reschedules = 0U;
    a->last_route_signature = UINT64_MAX;
    a->route_coalesced = a->route_duplicate = a->timer_mod_count = 0U;
    a->trace_cap1 = a->trace_t12 = a->trace_cross_cap_pairs = 0U;
    a->trace_cap_t12_pairs = a->trace_chain_pairs = 0U;
    a->trace_cap1_unpaired = a->trace_t12_unpaired = 0U;
    a->trace_cross_overwrites = a->trace_cap_overwrites = 0U;
    a->trace_cross_cap_last = a->trace_cap_t12_last = 0U;
    a->trace_cross_cap_max = a->trace_cap_t12_max = 0U;
    a->trace_cross_cap_min = a->trace_cap_t12_min = UINT32_MAX;
    a->trace_cross_cap_sum = a->trace_cap_t12_sum = 0U;
    a->trace_last_cross_ns = a->trace_last_cap_ns =
        a->trace_last_t12_ns = 0;
    a->trace_cross_pending = a->trace_cap_pending = false;
    a->trace_cap_linked_cross = false;
    a->stage_count = a->stage_index = a->max_frames = 0U;
    a->total_frames = a->target_frames = a->sent = 0U;
    a->last_dshot = a->crossings = a->analog_updates = 0U;
    a->powered_samples = a->last_phase = a->last_falling = 0U;
    a->current_stage = a->error_code = 0U;
    a->epoch_valid = a->running = a->done = false;
    a->start_ns = a->end_ns = a->phase_epoch_ns = 0;
    a->last_sample_word = 0U;
    a->p1_nfault_enable = a->p1_nfault_assert_frame =
        a->p1_nfault_release_frame = a->p1_nfault_events = 0U;
    a->p1_oc_enable = a->p1_oc_assert_frame = a->p1_oc_release_frame = 0U;
    a->p1_oc_channel = a->p1_oc_events = 0U;
    a->p1_oc_active = false;
    a->live_override_enabled = a->live_permille = 0U;
    a->live_changes = a->live_last_applied_frame = 0U;
    a->stage_seen_mask = a->stage_route_transitions = 0U;
    a->last_observed_state = UINT32_MAX;
    a->vector_commits = a->vector_unchanged = 0U;
}

static void am13e_auto_fail(AM13EAutoSITL *a, uint32_t reason)
{
    a->error_code = reason;
    a->running = false;
    if (a->dshot_timer) timer_del(a->dshot_timer);
    if (a->bemf_timer) timer_del(a->bemf_timer);
}

static bool am13e_auto_validate(AM13EAutoSITL *a)
{
    uint64_t total = 0;
    if (!a->stage_count || a->stage_count > AM13E_AUTO_MAX_STAGES) {
        return false;
    }
    for (unsigned i = 0; i < a->stage_count; ++i) {
        AM13EAutoStage *s = &a->stages[i];
        if (!s->duration_ms || s->duration_ms > 120000U ||
            !s->update_ms || s->duration_ms % s->update_ms ||
            s->from_permille > 1000U || s->to_permille > 1000U) {
            return false;
        }
        /* Contract: all ramp interpolation values are whole 0.1% units.
         * Reject a schedule instead of silently quantizing its semantics. */
        uint64_t mag = s->from_permille > s->to_permille ?
                       s->from_permille - s->to_permille :
                       s->to_permille - s->from_permille;
        if (mag * s->update_ms % s->duration_ms) {
            return false;
        }
        total += s->duration_ms;
        if (total > 1000000U) {
            return false;
        }
    }
    if (a->p1_nfault_enable && (!a->machine->native_motor.enabled ||
        !a->p1_nfault_assert_frame ||
        a->p1_nfault_assert_frame >= a->p1_nfault_release_frame ||
        a->p1_nfault_release_frame >= total)) {
        return false; /* no physical fault scheduled outside live frames */
    }
    if (a->p1_oc_enable &&
        (!a->machine->native_motor.enabled ||
         a->p1_nfault_enable ||
         a->p1_oc_channel>2U ||
         !a->p1_oc_assert_frame ||
         a->p1_oc_assert_frame>=a->p1_oc_release_frame ||
         a->p1_oc_release_frame>=total)) {
        return false; /* never mix fault classes or accept no-active interval */
    }
    a->total_frames = total; /* Exactly 1ms per DShot frame. */
    a->target_frames = a->max_frames ? a->max_frames : a->total_frames;
    return a->target_frames > 0U && a->target_frames <= a->total_frames;
}

/* Opt-in deterministic FC diagnostic. No Host/QTest start command,
 * no guest readiness trigger, and no change to the physical PA26 source
 * callback, 1kHz timeline, native motor, or original firmware.
 * These stage words exactly match e62-native-p0-smoke.json. */
/* EXPERIMENT branch only: exact DShot600 original Direct20 scenario,
 * no Host pacing, Guest register modifications, or synthetic commutation.
 * A clean 1ms source per frame, from the QEMU virtual reset epoch.
 */
/* SIM_ONLY preboot FC scenario matrix; deliberately uses the EXACT
 * immutable original JSON stage words, but a patched experimental ELF.
 * No QTest/Host writes into Guest motor state; real PA26 DShot, CMPSS,
 * ECAP1 and TIMG12 path remains guest-owned.
 */
static void am13e_auto_arm_experimental_profile(AM13EAutoSITL *a,
                                                 const char *profile)
{
    static const AM13EAutoStage smoke[] = {
        {1500U,0U,0U,1U},{1000U,0U,200U,5U},
        {300U,200U,200U,1U},{200U,0U,0U,1U},
    };
    static const AM13EAutoStage gentle[] = {
        {1500U,0U,0U,1U},{2000U,0U,100U,20U},
        {1000U,100U,100U,1U},{500U,0U,0U,1U},
    };
    static const AM13EAutoStage steps[] = {
        {1500U,0U,0U,1U},{500U,100U,100U,1U},
        {500U,200U,200U,1U},{500U,300U,300U,1U},
        {300U,0U,0U,1U},
    };
    static const AM13EAutoStage ramp100[] = {
        {1500U,0U,0U,1U},{100U,0U,200U,5U},
        {1000U,200U,200U,1U},{200U,0U,0U,1U},
    };
    static const AM13EAutoStage ramp500[] = {
        {1500U,0U,0U,1U},{500U,0U,200U,5U},
        {1000U,200U,200U,1U},{200U,0U,0U,1U},
    };
    const AM13EAutoStage *stages = NULL;
    unsigned count = 0;
    if (!strcmp(profile, "smoke")) {
        stages=smoke;count=G_N_ELEMENTS(smoke);
    } else if (!strcmp(profile, "gentle")) {
        stages=gentle;count=G_N_ELEMENTS(gentle);
    } else if (!strcmp(profile, "steps")) {
        stages=steps;count=G_N_ELEMENTS(steps);
    } else if (!strcmp(profile, "ramp100")) {
        stages=ramp100;count=G_N_ELEMENTS(ramp100);
    } else if (!strcmp(profile, "ramp500")) {
        stages=ramp500;count=G_N_ELEMENTS(ramp500);
    } else {
        error_report("E62 invalid experimental physical-FC profile");
        exit(EXIT_FAILURE);
    }
    g_assert(a->dshot_timer && a->machine->native_motor.enabled);
    g_assert(!a->running && !a->done && !a->error_code);
    memcpy(a->stages, stages, count * sizeof(*stages));
    a->stage_count = count;
    if (!am13e_auto_validate(a) ||
        a->target_frames != a->total_frames) {
        error_report("E62 experimental FC scenario contract invalid");
        exit(EXIT_FAILURE);
    }
    a->start_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 100U;
    a->running = true;
    timer_mod(a->dshot_timer,a->start_ns);
}

static void am13e_auto_arm_experimental_direct20(AM13EAutoSITL *a)
{
    static const AM13EAutoStage stages[] = {
        {1500U, 0U, 0U, 1U},
        {1500U, 200U, 200U, 1U},
        {300U, 0U, 0U, 1U},
    };
    g_assert(a->dshot_timer && a->machine->native_motor.enabled);
    g_assert(!a->running && !a->done && !a->error_code);
    memcpy(a->stages, stages, sizeof(stages));
    a->stage_count = G_N_ELEMENTS(stages);
    if (!am13e_auto_validate(a) || a->target_frames != 3300U) {
        error_report("E62 experimental Direct20 FC stage contract invalid");
        exit(EXIT_FAILURE);
    }
    a->start_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 100U;
    a->running = true;
    timer_mod(a->dshot_timer, a->start_ns);
}

static void am13e_auto_arm_differential_smoke(AM13EAutoSITL *a)
{
    static const AM13EAutoStage stages[] = {
        {1500U, 0U, 0U, 1U},
        {1000U, 0U, 200U, 5U},
        {300U, 200U, 200U, 1U},
        {200U, 0U, 0U, 1U},
    };
    g_assert(a->dshot_timer && a->machine->native_motor.enabled);
    g_assert(!a->running && !a->done && !a->error_code);
    memcpy(a->stages, stages, sizeof(stages));
    a->stage_count = G_N_ELEMENTS(stages);
    if (!am13e_auto_validate(a) || a->target_frames != 3000U) {
        error_report("E62 deterministic FC smoke stage contract invalid");
        exit(EXIT_FAILURE);
    }
    /* At machine reset, virtual time is at its initial epoch. We never
     * inspect host wall time or use Guest SRAM/IRQ to decide when to start.
     * First expiry may be serviced on the next QEMU icount boundary;
     * the original observed nanosecond timestamp must still be audited. */
    a->start_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 100U;
    a->running = true;
    timer_mod(a->dshot_timer, a->start_ns);
}

static uint32_t am13e_auto_dshot_value(uint32_t p)
{
    if (!p) return 0U;
    uint32_t n = 1999U * p;
    uint32_t q = n / 1000U, rem = n % 1000U;
    if (rem > 500U || (rem == 500U && (q & 1U))) ++q;
    return 48U + q;
}

static uint32_t am13e_auto_target_for_frame(AM13EAutoSITL *a,
                                             uint32_t index)
{
    uint32_t position = index;
    for (unsigned i = 0; i < a->stage_count; ++i) {
        AM13EAutoStage *s = &a->stages[i];
        if (position < s->duration_ms) {
            uint32_t stepped = (position / s->update_ms) * s->update_ms;
            int64_t span = (int64_t)s->to_permille -
                           (int64_t)s->from_permille;
            int64_t permille = (int64_t)s->from_permille +
                               span * stepped / s->duration_ms;
            a->current_stage = i;
            return am13e_auto_dshot_value((uint32_t)permille);
        }
        position -= s->duration_ms;
    }
    return UINT32_MAX;
}

static bool am13e_auto_wire_frame(AM13EAutoSITL *a, uint32_t throttle)
{
    AM13EPA26Wave *w = &a->machine->pa26_wave;
    if (throttle != 0U && (throttle < 48U || throttle > 2047U)) {
        return false;
    }
    if (w->running || (w->queued && w->delivered != w->queued)) {
        return false;
    }
    /* This is the exact native PA26 external edge queue ABI, NOT a
     * decoder/guest callback. The original wire event invokes the
     * existing am13e_sim_pa26_write -> TIMG4 CC0 -> DMA0 CH2 path. */
    am13e_pa26_wave_reset(w);
    uint32_t data = throttle << 1U;
    uint32_t frame = (data << 4U) |
        ((data ^ (data >> 4U) ^ (data >> 8U)) & 15U);
    uint32_t previous_high = 0U;
    for (int bit = 15; bit >= 0; --bit) {
        uint32_t high = (frame & (1U << bit)) ? 125U : 63U;
        w->delta_ns[w->queued] = bit == 15 ? 10000U :
                               10U * (167U - previous_high);
        w->levels[w->queued++] = 1U;
        w->delta_ns[w->queued] = 10U * high;
        w->levels[w->queued++] = 0U;
        previous_high = high;
    }
    if (w->queued != 32U) {
        return false;
    }
    w->running = true;
    timer_mod(w->timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
              w->delta_ns[0]);
    return true;
}

/* Stage-end hardware checkpoint is latched by QEMU's frame timer.
 * These are test-fixture PA26/DMA counters, never Guest CRC statements. */
static void am13e_auto_checkpoint(AM13EAutoSITL *a, unsigned stage,
                                  int64_t now, bool complete)
{
    if (stage >= a->stage_count) {
        am13e_auto_fail(a, 6U);
        return;
    }
    AM13EAutoStageEvidence *e = &a->stage_evidence[stage];
    e->valid = true;
    e->completed = complete;
    e->sent = a->sent;
    e->capture = a->machine->sim_pa26_captures;
    e->dma = a->machine->sim_pa26_dma_beats;
    e->crossings = a->crossings;
    e->analog_updates = a->analog_updates;
    e->bemf_timer_callbacks = a->bemf_timer_callbacks;
    e->phase_polarity_mask = a->stage_seen_mask;
    e->route_transitions = a->stage_route_transitions;
    a->stage_seen_mask = a->stage_route_transitions = 0U;
    a->last_observed_state = UINT32_MAX;
    e->elapsed_ns = now >= a->start_ns ?
                    (uint64_t)(now - a->start_ns) : 0U;
}

static void am13e_auto_dshot_event(void *opaque)
{
    AM13EAutoSITL *a = opaque;
    if (!a->running) return;
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    if (a->sent >= a->target_frames) {
        bool full_stage = a->sent == a->total_frames;
        am13e_auto_checkpoint(a, a->current_stage, now, full_stage);
        a->end_ns = now;
        a->running = false;
        a->done = true;
        if (a->bemf_timer) timer_del(a->bemf_timer);
        return;
    }
    /* Exact QEMU-clock external fault fixture. It is NOT a Guest
     * TZCLR/IRQ write or a Host poll-injected level. PA22 asserted
     * active-low at a chosen frame boundary and subsequently released.
     * Hardware trip latch persistence remains original hardware policy.
     */
    AM13EMachineState *machine=a->machine;
    if (a->p1_nfault_enable &&
        (a->sent==a->p1_nfault_assert_frame ||
         a->sent==a->p1_nfault_release_frame)) {
        bool asserted = a->sent==a->p1_nfault_assert_frame;
        machine->gpio[0].nfault_asserted=asserted;
        am13e_g13b2_trip_update(machine);
        ++a->p1_nfault_events;
        am13e_p0_event(machine,"NFAULT_EDGE",
                       asserted,a->sent,
                       machine->pwm4.reg[0xb0U/4U],
                       machine->pwm4.irqs,0,0);
    }
    /* Separate, bounded SIM_ONLY analog current-SENSOR excursion.
     * QEMU physical source callback, not the Host, changes the sample;
     * original CMPSS1/2/3 -> Trip3 -> MCPWM4 IRQ remains guest-owned.
     * Log outside E62_P0_EVENT so the Original P1 event schema stays
     * bit-for-bit unmodified. This is not a motor-current measurement.
     */
    if (a->p1_oc_enable &&
        (a->sent==a->p1_oc_assert_frame ||
         a->sent==a->p1_oc_release_frame)) {
        const bool asserted=a->sent==a->p1_oc_assert_frame;
        a->p1_oc_active=asserted;
        am13e_native_motor_publish_oc(&machine->native_motor);
        ++a->p1_oc_events;
        error_report("E62_NATIVE_EXTERNAL_OC_EDGE vns=%" PRId64
                     " frame=%u channel=%u asserted=%u "
                     "code=%u trip=0x%x irq=0x%x",
                     now,a->sent,a->p1_oc_channel,asserted,
                     machine->trip.oc_input[a->p1_oc_channel],
                     machine->pwm4.reg[0xb0U/4U],machine->pwm4.irqs);
    }
    unsigned previous_stage = a->current_stage;
    uint32_t target = am13e_auto_target_for_frame(a, a->sent);
    if (a->live_override_enabled) {
        target = am13e_auto_dshot_value(a->live_permille);
        a->live_last_applied_frame = a->sent;
    }
    if (a->sent && a->current_stage != previous_stage) {
        am13e_auto_checkpoint(a, previous_stage, now, true);
    }
    if (target == UINT32_MAX || !am13e_auto_wire_frame(a, target)) {
        am13e_auto_fail(a, 2U); /* Wire busy/malformed input. */
        return;
    }
    /* Source-authentic independent FC commanded frame; the 1kHz
     * physical PA26 wave is scheduled above. This does not imply
     * original Guest CRC acceptance or a measured motor response. */
    am13e_p0_event(a->machine,"DSHOT",
                   a->sent,a->current_stage,target,
                   a->live_override_enabled,a->live_permille,0);
    a->last_dshot = target;
    ++a->sent;
    /* Absolute deadlines: timer callback overhead must never turn
     * virtual-time 1kHz spacing into accumulated per-frame drift. */
    timer_mod(a->dshot_timer,
              a->start_ns + (int64_t)a->sent * AM13E_AUTO_FRAME_NS);
}

/* Ready means original Guest has actually powered/configured the
 * native PWM/CMPSS/ECAP route; unlike a motor plant no rotor is inferred. */
static bool am13e_auto_feedback_ready(AM13EMachineState *s,
                                     AM13ESimFeedback *f, unsigned phase)
{
    return s->pwm4.running &&
        !!(s->sim_perclkcr & 1U) &&
        !!(s->sim_mc_power & AM13E_SIM_PWM_POWER_BIT) &&
        am13e_g10_cmp_powered(f) && am13e_g10_ecap_powered(f) &&
        phase < 3U && (f->ecctl0 & 0x7fU) == 45U &&
        !!(f->ecctl1 & 0x100U) && !!(f->ecctl2 & 0x10U) &&
        !!(f->eceint & 0x2U) &&
        (f->cmp[0] & 0x800cU) == 0x8008U &&
        !(s->pwm4.reg[0xb0U / 4U] & 0x00060000U);
}

/* Register change notifications only. Re-schedule 100ns in the future
 * to let a Guest update comparator mux + polarity in separate writes.
 * No timer when disabled: future Guest register writes re-activate it.
 * A fingerprint suppresses unchanged PWM-zero/DAC-sync notifications. */
static void am13e_auto_route_changed(AM13EMachineState *s)
{
    AM13EAutoSITL *a = &s->auto_sitl;
    if (!a->running || !a->bemf_timer || s->native_motor.enabled) {
        return;
    }
    AM13ESimFeedback *f = &s->feedback;
    unsigned phase = s->sim_mc_mux[0] & 7U;
    uint32_t dac = f->cmp[0x0eU / 2U] & 0xfffU;
    uint64_t fingerprint =
        (uint64_t)phase | ((uint64_t)(f->ecctl1 & 1U) << 3U) |
        ((uint64_t)dac << 4U) |
        ((uint64_t)am13e_auto_feedback_ready(s, f, phase) << 16U) |
        ((uint64_t)f->cmp[0] << 17U) |
        ((uint64_t)(f->cmp[0x30U / 2U] & 0x7fffU) << 33U);
    if (fingerprint == a->last_route_signature) {
        ++a->route_duplicate;
        return;
    }
    a->last_route_signature = fingerprint;
    ++a->route_reschedules; /* meaningful route state notifications */
    int64_t due = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
                  AM13E_AUTO_ROUTE_REEVAL_NS;
    /* EARLIEST-WINS: avoid pushing a pending event later by 100ns.
     * If a native Zero Crossing is scheduled later, the route edit
     * still preempts it at due. This never defers a pending evaluation
     * relative to G13B6; it can only evaluate up to 100ns sooner. */
    if (timer_pending(a->bemf_timer) &&
        timer_expire_time_ns(a->bemf_timer) <= due) {
        ++a->route_coalesced;
        return;
    }
    timer_mod(a->bemf_timer, due);
    ++a->timer_mod_count;
}

static void am13e_auto_analog_event(void *opaque)
{
    AM13EAutoSITL *a = opaque;
    if (!a->running || a->machine->native_motor.enabled) return;
    ++a->bemf_timer_callbacks;
    AM13EMachineState *s = a->machine;
    AM13ESimFeedback *f = &s->feedback;
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    uint32_t words[3] = {0x10000U | 2048U,
                         0x10000U | 2048U,
                         0x10000U | 2048U};
    unsigned phase = s->sim_mc_mux[0] & 7U;
    bool ready = am13e_auto_feedback_ready(s, f, phase);
    int64_t next_crossing_ns = 0;

    if (ready) {
        uint32_t dac = f->cmp[0x0eU / 2U] & 0xfffU;
        uint32_t falling = !!(f->ecctl1 & 1U);
        if (dac >= 128U && dac <= 3967U) {
            ++a->powered_samples;
            if (!a->epoch_valid || phase != a->last_phase ||
                falling != a->last_falling) {
                a->last_phase = phase;
                a->last_falling = falling;
                a->epoch_valid = true;
                a->phase_epoch_ns = now;
            }
            uint64_t phase_time = (uint64_t)(now - a->phase_epoch_ns);
            bool crossed = !!((phase_time / AM13E_AUTO_BEMF_CROSS_NS) & 1U);
            uint32_t high = dac + 128U, low = dac - 128U;
            words[phase] = 0x10000U |
                (crossed == !!falling ? low : high);
            /* Absolute one-shot zero-crossing deadlines prevent drift;
             * 750us polarity flips continue if the original Guest
             * chooses not to commutate. A changed mux/polarity restarts
             * the half-cycle at the next deferred route notification. */
            next_crossing_ns = a->phase_epoch_ns +
                (int64_t)(phase_time / AM13E_AUTO_BEMF_CROSS_NS + 1U) *
                AM13E_AUTO_BEMF_CROSS_NS;
        } else {
            a->epoch_valid = false;
        }
    } else {
        a->epoch_valid = false;
    }

    uint32_t previous = a->last_sample_word;
    uint32_t writes_before = a->analog_updates;
    if (!am13e_g10_stim_vector(f, words, &a->analog_updates)) {
        am13e_auto_fail(a, 3U);
        return;
    }
    if (a->analog_updates == writes_before) {
        ++a->vector_unchanged;
    } else {
        ++a->vector_commits;
    }
    if (ready && phase < 3U && a->epoch_valid) {
        uint32_t code = 2U * phase + !!(f->ecctl1 & 1U);
        a->stage_seen_mask |= 1U << code;
        if (a->last_observed_state != UINT32_MAX &&
            code != a->last_observed_state) {
            ++a->stage_route_transitions;
        }
        a->last_observed_state = code;
    }
    if (ready && words[phase] != previous &&
        previous && a->epoch_valid) {
        ++a->crossings; /* stimulus transitions, NOT native CAP1. */
        if (a->trace_cross_pending) {
            ++a->trace_cross_overwrites;
        }
        a->trace_last_cross_ns = now;
        a->trace_cross_pending = true;
    }
    a->last_sample_word = next_crossing_ns ? words[phase] : 0U;
    if (next_crossing_ns > now) {
        if (!timer_pending(a->bemf_timer) ||
            timer_expire_time_ns(a->bemf_timer) != next_crossing_ns) {
            timer_mod(a->bemf_timer, next_crossing_ns);
            ++a->timer_mod_count;
        }
    }
    /* No polling when not ready; MMIO route changes reactivate timer. */
}


/* Temporal association only, bounded and non-invasive. These callback
 * hooks observe events AFTER native comparator/capture and TIMER logic.
 * An adjacent timestamp is evidence of ordering, NOT proof of a causal
 * Guest ISR or a motor physics/rotor trajectory. */
#define AM13E_AUTO_TRACE_PAIR_MAX_NS INT64_C(3000000)
static void am13e_auto_trace_cap1(AM13EMachineState *s)
{
    AM13EAutoSITL *a = &s->auto_sitl;
    if (!a->running) return;
    const int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    ++a->trace_cap1;
    AM13ESimFeedback *fb = &s->feedback;
    am13e_p0_event(s, "CAP1", fb->cap[0],
                   s->sim_mc_mux[0]&7U,fb->ecflg,fb->eceint,0,0);
    bool linked = false;
    if (a->trace_cross_pending && now >= a->trace_last_cross_ns &&
        now - a->trace_last_cross_ns <= AM13E_AUTO_TRACE_PAIR_MAX_NS) {
        uint32_t ns = (uint32_t)(now - a->trace_last_cross_ns);
        a->trace_cross_cap_last = ns;
        a->trace_cross_cap_min = MIN(a->trace_cross_cap_min, ns);
        a->trace_cross_cap_max = MAX(a->trace_cross_cap_max, ns);
        a->trace_cross_cap_sum += ns;
        ++a->trace_cross_cap_pairs;
        linked = true;
    } else {
        ++a->trace_cap1_unpaired;
    }
    a->trace_cross_pending = false;
    if (a->trace_cap_pending) {
        ++a->trace_cap_overwrites;
    }
    a->trace_last_cap_ns = now;
    a->trace_cap_pending = true;
    a->trace_cap_linked_cross = linked;
}

static void am13e_auto_trace_timg12_zero(AM13ESimTimer *t)
{
    if (t->base != 0x40188000U || !t->esc_sim ||
        !(t->irq_mask[0] & AM13E_SIM_TIMER_ZERO) || !t->machine) {
        return;
    }
    /* gtimer belongs to the same AM13E Machine as its GPRCM owner.
     * Obtain it through its init-time linked machine pointer. */
    AM13EMachineState *s = t->machine;
    AM13EAutoSITL *a = &s->auto_sitl;
    if (!a->running) return;
    const int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    ++a->trace_t12;
    am13e_p0_event(s, "TIMG12", t->irq_raw[0],
                   t->irq_mask[0],t->reg[0x808U / 4U],0,0,0);
    a->trace_last_t12_ns = now;
    if (a->trace_cap_pending && now >= a->trace_last_cap_ns &&
        now - a->trace_last_cap_ns <= AM13E_AUTO_TRACE_PAIR_MAX_NS) {
        uint32_t ns = (uint32_t)(now - a->trace_last_cap_ns);
        a->trace_cap_t12_last = ns;
        a->trace_cap_t12_min = MIN(a->trace_cap_t12_min, ns);
        a->trace_cap_t12_max = MAX(a->trace_cap_t12_max, ns);
        a->trace_cap_t12_sum += ns;
        ++a->trace_cap_t12_pairs;
        if (a->trace_cap_linked_cross) ++a->trace_chain_pairs;
    } else {
        ++a->trace_t12_unpaired;
    }
    a->trace_cap_pending = false;
}

static MemTxResult am13e_auto_read(void *opaque, hwaddr off,
                                   uint64_t *v, unsigned size,
                                   MemTxAttrs attrs)
{
    AM13EAutoSITL *a = opaque;
    if (!a->machine->esc_sim || size != 4U || (off & 3U)) {
        return MEMTX_ERROR;
    }
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    /* START arms virtual timers 100ns in the future. Before that first
     * event, negative elapsed must report zero, never wrap to UINT64_MAX. */
    uint64_t ns = a->done ? (uint64_t)(a->end_ns - a->start_ns) :
                  a->running && now >= a->start_ns ?
                  (uint64_t)(now - a->start_ns) : 0U;
    switch (off) {
    case 0x00: *v = AM13E_AUTO_MAGIC; break;
    case 0x08: *v = (a->running ? 1U : 0U) |
                    (a->done ? 2U : 0U) |
                    (a->error_code ? 4U : 0U); break;
    case 0x0c: *v = a->stage_count; break;
    case 0x10: *v = a->stage_index; break;
    case 0x14: *v = a->stages[a->stage_index].duration_ms; break;
    case 0x18: *v = a->stages[a->stage_index].from_permille; break;
    case 0x1c: *v = a->stages[a->stage_index].to_permille; break;
    case 0x20: *v = a->stages[a->stage_index].update_ms; break;
    case 0x24: *v = a->max_frames; break;
    case 0x28: *v = a->sent; break;
    case 0x2c: *v = a->target_frames; break;
    case 0x30: *v = a->last_dshot; break;
    case 0x34: *v = a->crossings; break;
    case 0x38: *v = ns / AM13E_AUTO_FRAME_NS; break;
    case 0x3c: *v = a->error_code; break;
    case 0x40: *v = (uint32_t)ns; break;
    case 0x44: *v = ns >> 32U; break;
    case 0x48: *v = a->analog_updates; break;
    case 0x4c: *v = a->powered_samples; break;
    case 0x50: *v = a->current_stage; break;
    case 0x54: *v = a->machine->sim_pa26_captures; break;
    case 0x58: *v = a->machine->sim_pa26_dma_beats; break;
    case 0x5c: *v = a->stage_query; break;
    case 0x60: *v = a->stage_evidence[a->stage_query].sent; break;
    case 0x64: *v = a->stage_evidence[a->stage_query].capture; break;
    case 0x68: *v = a->stage_evidence[a->stage_query].dma; break;
    case 0x6c: *v = a->stage_evidence[a->stage_query].crossings; break;
    case 0x70:
        *v = (a->stage_evidence[a->stage_query].valid ? 1U : 0U) |
             (a->stage_evidence[a->stage_query].completed ? 2U : 0U);
        break;
    case 0x74:
        *v = a->stage_evidence[a->stage_query].elapsed_ns / AM13E_AUTO_FRAME_NS;
        break;
    case 0x78: *v = a->stage_evidence[a->stage_query].bemf_timer_callbacks; break;
    case 0x7c: *v = a->stage_evidence[a->stage_query].analog_updates; break;
    case 0x80: *v = a->bemf_timer_callbacks; break;
    case 0x84: *v = a->route_reschedules; break;
    case 0x88: *v = 4U; break; /* G13B7.1 corrected sampler ABI */
    case 0x8c: *v = a->route_reschedules; break;
    case 0x90: *v = a->route_coalesced; break;
    case 0x94: *v = a->timer_mod_count; break;
    case 0x98: *v = a->route_duplicate; break;
    case 0x9c: *v = a->trace_cap1; break;
    case 0xa0: *v = a->trace_t12; break;
    case 0xa4: *v = a->trace_cross_cap_pairs; break;
    case 0xa8: *v = a->trace_cap_t12_pairs; break;
    case 0xac: *v = a->trace_chain_pairs; break;
    case 0xb0: *v = a->trace_cross_cap_last; break;
    case 0xb4: *v = a->trace_cap_t12_last; break;
    case 0xb8: *v = a->trace_cross_cap_max; break;
    case 0xbc: *v = a->trace_cap_t12_max; break;
    case 0xc0: *v = a->trace_cross_cap_pairs ?
                    a->trace_cross_cap_min : 0; break;
    case 0xc4: *v = a->trace_cap_t12_pairs ?
                    a->trace_cap_t12_min : 0; break;
    case 0xc8: *v = (uint32_t)a->trace_cross_cap_sum; break;
    case 0xcc: *v = a->trace_cross_cap_sum >> 32U; break;
    case 0xd0: *v = (uint32_t)a->trace_cap_t12_sum; break;
    case 0xd4: *v = a->trace_cap_t12_sum >> 32U; break;
    case 0xd8: *v = a->trace_cap1_unpaired; break;
    case 0xdc: *v = a->trace_t12_unpaired; break;
    case 0xe0: *v = a->trace_cross_overwrites; break;
    case 0xe4: *v = a->trace_cap_overwrites; break;
    case 0xe8: *v = a->trace_last_cross_ns >= a->start_ns ?
                    (uint32_t)(a->trace_last_cross_ns - a->start_ns) : 0; break;
    case 0xec: *v = a->trace_last_cross_ns >= a->start_ns ?
                    (uint64_t)(a->trace_last_cross_ns - a->start_ns) >> 32U : 0; break;
    case 0xf0: *v = a->trace_last_cap_ns >= a->start_ns ?
                    (uint32_t)(a->trace_last_cap_ns - a->start_ns) : 0; break;
    case 0xf4: *v = a->trace_last_cap_ns >= a->start_ns ?
                    (uint64_t)(a->trace_last_cap_ns - a->start_ns) >> 32U : 0; break;
    case 0xf8: *v = a->trace_last_t12_ns >= a->start_ns ?
                    (uint32_t)(a->trace_last_t12_ns - a->start_ns) : 0; break;
    case 0xfc: *v = a->trace_last_t12_ns >= a->start_ns ?
                    (uint64_t)(a->trace_last_t12_ns - a->start_ns) >> 32U : 0; break;
    case 0x100: *v = a->stage_evidence[a->stage_query].phase_polarity_mask; break;
    case 0x104: *v = a->stage_evidence[a->stage_query].route_transitions; break;
    case 0x108: *v = a->vector_unchanged; break;
    case 0x10c: *v = a->vector_commits; break;
    case 0x110: *v = a->stage_seen_mask; break;
    case 0x114: *v = a->stage_route_transitions; break;
    case 0x118: *v = UINT32_C(0x53363134); break; /* S614 schema */
    case 0x120: *v = a->p1_nfault_assert_frame; break;
    case 0x124: *v = a->p1_nfault_release_frame; break;
    case 0x128: *v = a->p1_nfault_enable; break;
    case 0x12c: *v = a->p1_nfault_events; break;
    case 0x130: *v = a->live_override_enabled; break;
    case 0x134: *v = a->live_permille; break;
    case 0x138: *v = a->live_changes; break;
    case 0x13c: *v = a->live_last_applied_frame; break;
    case 0x140: *v = a->p1_oc_assert_frame; break;
    case 0x144: *v = a->p1_oc_release_frame; break;
    case 0x148: *v = a->p1_oc_channel; break;
    case 0x14c: *v = a->p1_oc_enable; break;
    case 0x150: *v = a->p1_oc_events; break;
    default: return MEMTX_ERROR;
    }
    return MEMTX_OK;
}

static MemTxResult am13e_auto_write(void *opaque, hwaddr off,
                                    uint64_t value, unsigned size,
                                    MemTxAttrs attrs)
{
    AM13EAutoSITL *a = opaque;
    uint32_t v = (uint32_t)value;
    if (!a->machine->esc_sim || size != 4U || (off & 3U) ||
        value != v) {
        return MEMTX_ERROR;
    }
    if (off == 0x04) {
        if (v == 2U && a->running) {
            am13e_auto_fail(a, 5U);
            return MEMTX_OK;
        }
        if (v == 3U && !a->running) {
            am13e_auto_reset(a);
            return MEMTX_OK;
        }
        if (v != 1U || a->running || a->done || a->error_code ||
            !am13e_auto_validate(a) ||
            a->machine->pa26_wave.running) {
            return MEMTX_ERROR;
        }
        a->start_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 100U;
        a->running = true;
        timer_mod(a->dshot_timer, a->start_ns);
        /* Native motor mode owns analog feedback: never start timed fake BEMF. */
        if (!a->machine->native_motor.enabled) {
            timer_mod(a->bemf_timer, a->start_ns + AM13E_AUTO_ROUTE_REEVAL_NS);
        }
        return MEMTX_OK;
    }
    if (off == 0x5c && v < AM13E_AUTO_MAX_STAGES) {
        a->stage_query = v; /* non-silicon, read-only evidence selection */
        return MEMTX_OK;
    }
    /* Deliberate sole live write exception: independent external
     * flight-controller throttle, applied at NEXT physical DShot frame.
     * No Guest SRAM/UART/CLI/IRQ/PWM/CFG writes. Every change leaves a
     * source-owned QEMU virtual timestamp and next-frame index.
     */
    if (a->running && !a->done && !a->error_code &&
        (off == 0x130 || off == 0x134)) {
        if (off == 0x130 && v > 1U) return MEMTX_ERROR;
        if (off == 0x134 && v > 1000U) return MEMTX_ERROR;
        if (off == 0x130) {
            a->live_override_enabled = v;
        } else {
            a->live_permille = v;
        }
        ++a->live_changes;
        am13e_p0_event(a->machine,"THROT_SET",
                       a->sent,a->live_override_enabled,
                       a->live_permille,a->live_changes,0,0);
        return MEMTX_OK;
    }
    if (a->running || a->done || a->error_code) {
        return MEMTX_ERROR;
    }
    switch (off) {
    case 0x0c:
        if (!v || v > AM13E_AUTO_MAX_STAGES) return MEMTX_ERROR;
        a->stage_count = v; return MEMTX_OK;
    case 0x10:
        if (v >= AM13E_AUTO_MAX_STAGES) return MEMTX_ERROR;
        a->stage_index = v; return MEMTX_OK;
    case 0x14: a->stages[a->stage_index].duration_ms = v; return MEMTX_OK;
    case 0x18: a->stages[a->stage_index].from_permille = v; return MEMTX_OK;
    case 0x1c: a->stages[a->stage_index].to_permille = v; return MEMTX_OK;
    case 0x20: a->stages[a->stage_index].update_ms = v; return MEMTX_OK;
    case 0x24: a->max_frames = v; return MEMTX_OK;
    /* SIM_ONLY external PA22 physical level calendar. Never writable
     * while FC timer is running. No direct guest register writes. */
    case 0x120: a->p1_nfault_assert_frame = v; return MEMTX_OK;
    case 0x124: a->p1_nfault_release_frame = v; return MEMTX_OK;
    case 0x128:
        if (v>1U || (v && (!a->machine->native_motor.enabled ||
                          a->p1_oc_enable)))
            return MEMTX_ERROR;
        a->p1_nfault_enable = v;
        return MEMTX_OK;
    /* The source calendar, not the Host, may drive this analogue line.
     * It is a SIM_ONLY current-sense fault injection, not real load current. */
    case 0x140: a->p1_oc_assert_frame=v; return MEMTX_OK;
    case 0x144: a->p1_oc_release_frame=v; return MEMTX_OK;
    case 0x148:
        if(v>2U)return MEMTX_ERROR;
        a->p1_oc_channel=v;return MEMTX_OK;
    case 0x14c:
        if(v>1U || (v && (!a->machine->native_motor.enabled ||
                         a->p1_nfault_enable)))return MEMTX_ERROR;
        a->p1_oc_enable=v;return MEMTX_OK;
    default: return MEMTX_ERROR;
    }
}
static const MemoryRegionOps am13e_auto_ops = {
    .read_with_attrs = am13e_auto_read,
    .write_with_attrs = am13e_auto_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};
