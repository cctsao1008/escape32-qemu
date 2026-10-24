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
#define AM13E_AUTO_SIZE 0x100U
#define AM13E_AUTO_MAGIC UINT32_C(0x41323645) /* E62A */
#define AM13E_AUTO_MAX_STAGES 16U
#define AM13E_AUTO_FRAME_NS INT64_C(1000000)
#define AM13E_AUTO_BEMF_NS INT64_C(100000)
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
    a->stage_count = a->stage_index = a->max_frames = 0U;
    a->total_frames = a->target_frames = a->sent = 0U;
    a->last_dshot = a->crossings = a->analog_updates = 0U;
    a->powered_samples = a->last_phase = a->last_falling = 0U;
    a->current_stage = a->error_code = 0U;
    a->epoch_valid = a->running = a->done = false;
    a->start_ns = a->end_ns = a->phase_epoch_ns = 0;
    a->last_sample_word = 0U;
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
    a->total_frames = total; /* Exactly 1ms per DShot frame. */
    a->target_frames = a->max_frames ? a->max_frames : a->total_frames;
    return a->target_frames > 0U && a->target_frames <= a->total_frames;
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

static void am13e_auto_dshot_event(void *opaque)
{
    AM13EAutoSITL *a = opaque;
    if (!a->running) return;
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    if (a->sent >= a->target_frames) {
        a->end_ns = now;
        a->running = false;
        a->done = true;
        if (a->bemf_timer) timer_del(a->bemf_timer);
        return;
    }
    uint32_t target = am13e_auto_target_for_frame(a, a->sent);
    if (target == UINT32_MAX || !am13e_auto_wire_frame(a, target)) {
        am13e_auto_fail(a, 2U); /* Wire busy/malformed input. */
        return;
    }
    a->last_dshot = target;
    ++a->sent;
    /* Absolute deadlines: timer callback overhead must never turn
     * virtual-time 1kHz spacing into accumulated per-frame drift. */
    timer_mod(a->dshot_timer,
              a->start_ns + (int64_t)a->sent * AM13E_AUTO_FRAME_NS);
}

static void am13e_auto_analog_event(void *opaque)
{
    AM13EAutoSITL *a = opaque;
    if (!a->running) return;
    AM13EMachineState *s = a->machine;
    AM13ESimFeedback *f = &s->feedback;
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    uint32_t words[3] = {0x10000U | 2048U,
                         0x10000U | 2048U,
                         0x10000U | 2048U};
    unsigned phase = s->sim_mc_mux[0] & 7U;
    bool ready = s->pwm4.running &&
        !!(s->sim_perclkcr & 1U) &&
        !!(s->sim_mc_power & AM13E_SIM_PWM_POWER_BIT) &&
        am13e_g10_cmp_powered(f) && am13e_g10_ecap_powered(f) &&
        phase < 3U && (f->ecctl0 & 0x7fU) == 45U &&
        !!(f->ecctl1 & 0x100U) && !!(f->ecctl2 & 0x10U) &&
        !!(f->eceint & 0x2U) &&
        (f->cmp[0] & 0x800cU) == 0x8008U &&
        !(s->pwm4.reg[0xb0U / 4U] & 0x00060000U);
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
            uint64_t phase_time = (uint64_t)(now - a->phase_epoch_ns) %
                                  (2U * AM13E_AUTO_BEMF_CROSS_NS);
            bool crossed = phase_time >= AM13E_AUTO_BEMF_CROSS_NS;
            uint32_t high = dac + 128U, low = dac - 128U;
            words[phase] = 0x10000U |
                (crossed == !!falling ? low : high);
        }
    } else {
        a->epoch_valid = false;
    }
    uint32_t previous = a->last_sample_word;
    for (unsigned i = 0; i < 3U; ++i) {
        uint32_t word = f->phase_code[i] |
                        (f->phase_valid[i] ? 0x10000U : 0U);
        if (word == words[i]) continue;
        /* Existing QEMU SIM_ONLY stimulus entrypoint already implements
         * comparator routing/filtering; no CAP1/ISR is manufactured. */
        if (am13e_g10_stim_write(f, i * 4U, words[i], 4U,
                                MEMTXATTRS_UNSPECIFIED) != MEMTX_OK) {
            am13e_auto_fail(a, 3U);
            return;
        }
        ++a->analog_updates;
    }
    if (ready && words[phase] != previous &&
        previous && a->epoch_valid) {
        ++a->crossings; /* stimulus transitions, NOT native CAP1. */
    }
    a->last_sample_word = ready ? words[phase] : 0U;
    timer_mod(a->bemf_timer, now + AM13E_AUTO_BEMF_NS);
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
        timer_mod(a->bemf_timer, a->start_ns + AM13E_AUTO_BEMF_NS);
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
    default: return MEMTX_ERROR;
    }
}
static const MemoryRegionOps am13e_auto_ops = {
    .read_with_attrs = am13e_auto_read,
    .write_with_attrs = am13e_auto_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};
