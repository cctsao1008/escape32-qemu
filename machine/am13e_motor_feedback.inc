/*
 * G10 ECAP1 / CMPSS0 functional motor feedback model.
 * Register addresses and masks: TI AM13E SDK hw_ecap.h/hw_cmpss_lite.h.
 * No analog silicon timing accuracy or autonomous motor motion is claimed.
 * Analog phase values enter ONLY through the explicit ESC-SIM stimulus port.
 */
#define AM13E_G10_ECAP_BASE    0x40441000U
#define AM13E_G10_CMPSS_BASE   0x40460000U
#define AM13E_G10_STIM_BASE    0x5ffe2000U
#define AM13E_G10_ECAP_SIZE    0x40U
#define AM13E_G10_CMPSS_SIZE   0x74U
#define AM13E_G10_ECAP_POWER   (1U << 4)
#define AM13E_G10_CMPSS_POWER  (1U << 10)
#define AM13E_G10_ECAP_TICK_NS INT64_C(10) /* functional 100 MHz clock */
#define AM13E_G10_ECAP_EVENT_MASK 0x00feU

static bool am13e_g10_ecap_powered(AM13ESimFeedback *f)
{
    return f->machine->esc_sim &&
        !!(f->machine->sim_mc_power & AM13E_G10_ECAP_POWER);
}
static bool am13e_g10_cmp_powered(AM13ESimFeedback *f)
{
    return f->machine->esc_sim &&
        !!(f->machine->sim_mc_power & AM13E_G10_CMPSS_POWER);
}
static uint32_t am13e_g10_count(AM13ESimFeedback *f)
{
    if (!(f->ecctl2 & 0x0010U) || !am13e_g10_ecap_powered(f)) {
        return f->count_base;
    }
    int64_t dt = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) - f->epoch_ns;
    return f->count_base + (uint32_t)(MAX(dt, INT64_C(0)) /
                                       AM13E_G10_ECAP_TICK_NS);
}
static void am13e_g10_irq_update(AM13ESimFeedback *f)
{
    if (f->ecap_irq) {
        qemu_set_irq(f->ecap_irq,
                     !!(f->ecflg & f->eceint & AM13E_G10_ECAP_EVENT_MASK));
    }
}
static void am13e_g10_flags(AM13ESimFeedback *f, uint16_t mask)
{
    f->ecflg |= mask & AM13E_G10_ECAP_EVENT_MASK;
    if (f->ecflg & f->eceint & AM13E_G10_ECAP_EVENT_MASK) {
        f->ecflg |= 1U; /* global INT flag: qualifying enabled event */
    }
    am13e_g10_irq_update(f);
}
static void am13e_g10_ovf_rearm(AM13ESimFeedback *f)
{
    if (f->overflow_timer) {
        timer_del(f->overflow_timer);
    }
    if (!(f->ecctl2 & 0x10U) || !am13e_g10_ecap_powered(f)) {
        return;
    }
    uint64_t left = UINT64_C(0x100000000) - am13e_g10_count(f);
    uint64_t duration = left * AM13E_G10_ECAP_TICK_NS;
    timer_mod(f->overflow_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
              (int64_t)duration);
}
static void am13e_g10_ovf_event(void *opaque)
{
    AM13ESimFeedback *f = opaque;
    if (!am13e_g10_ecap_powered(f) || !(f->ecctl2 & 0x10U)) {
        return;
    }
    f->count_base = 0U;
    f->epoch_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    am13e_g10_flags(f, 0x20U); /* CTROVF from actual counter wrap */
    am13e_g10_ovf_rearm(f);
}
static void am13e_g10_stop_counter(AM13ESimFeedback *f)
{
    f->count_base = am13e_g10_count(f);
    f->epoch_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    if (f->overflow_timer) {
        timer_del(f->overflow_timer);
    }
}
static void am13e_g10_start_counter(AM13ESimFeedback *f)
{
    f->epoch_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    am13e_g10_ovf_rearm(f);
}

/* Edge enters the capture engine only from a correctly routed, enabled
 * CMPSS0 high comparator. ECAP does not manufacture a capture from time.
 */
static void am13e_g10_ecap_edge(AM13ESimFeedback *f, bool rising)
{
    if (!am13e_g10_ecap_powered(f) ||
        (f->ecctl0 & 0x7fU) != 45U ||
        !(f->ecctl2 & 0x10U) ||
        (f->ecctl2 & 0x200U) || f->oneshot_frozen) {
        return;
    }
    unsigned event = f->capture_index & 3U;
    bool want_falling = !!(f->ecctl1 & (1U << (2U * event)));
    if ((!rising) != want_falling) {
        return;
    }
    if (f->ecctl1 & 0x0100U) { /* CAPLDEN controls load, not flag */
        f->cap[event] = am13e_g10_count(f);
    }
    am13e_g10_flags(f, (uint16_t)(2U << event));
    unsigned wrap = ((f->ecctl2 >> 1U) & 3U) + 1U;
    if (++f->capture_index >= wrap) {
        f->capture_index = 0U;
        if (f->ecctl2 & 1U) {
            f->oneshot_frozen = true;
        }
    }
    if (f->ecctl1 & (1U << (2U * event + 1U))) {
        f->count_base = 0U;
        f->epoch_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
        am13e_g10_ovf_rearm(f);
    }
}
static bool am13e_g10_raw(AM13ESimFeedback *f)
{
    unsigned mux = f->machine->sim_mc_mux[0] & 7U;
    if (!am13e_g10_cmp_powered(f) ||
        !(f->cmp[0x00U / 2U] & 0x8000U) ||
        (f->cmp[0x00U / 2U] & 1U) || /* DAC comparator source only */
        mux >= 3U || !f->phase_valid[mux]) {
        return false;
    }
    bool raw = f->phase_code[mux] > (f->cmp[0x0eU / 2U] & 0x0fffU);
    return raw ^ !!(f->cmp[0x00U / 2U] & 2U);
}
static void am13e_g10_output(AM13ESimFeedback *f, bool level)
{
    if (f->filtered == level) {
        return;
    }
    f->filtered = level;
    if (level) {
        f->cmp_latch = true;
    }
    /* Firmware uses CTRIPHSEL=2 (majority filter). Other sources do
     * not borrow this filter path and silently produce an edge.
     */
    if ((f->cmp[0x00U / 2U] & 0x000cU) == 0x0008U) {
        am13e_g10_ecap_edge(f, level);
    }
}
static void am13e_g10_filter_done(void *opaque)
{
    AM13ESimFeedback *f = opaque;
    unsigned mux = f->machine->sim_mc_mux[0] & 7U;
    if (!am13e_g10_cmp_powered(f) ||
        !(f->cmp[0x00U / 2U] & 0x8000U) ||
        (f->cmp[0x30U / 2U] & 7U) != 0U ||
        mux >= 3U || !f->phase_valid[mux]) {
        return;
    }
    if (am13e_g10_raw(f) == f->filter_pending) {
        am13e_g10_output(f, f->filter_pending);
    }
}
static void am13e_g10_cmp_evaluate(AM13ESimFeedback *f)
{
    if (f->filter_timer) {
        timer_del(f->filter_timer);
    }
    unsigned mux = f->machine->sim_mc_mux[0] & 7U;
    if (!am13e_g10_cmp_powered(f) ||
        !(f->cmp[0x00U / 2U] & 0x8000U) ||
        mux >= 3U || !f->phase_valid[mux] ||
        (f->cmp[0x30U / 2U] & 7U) != 0U) {
        return;
    }
    f->filter_pending = am13e_g10_raw(f);
    if (f->filter_pending == f->filtered) {
        return;
    }
    /* DriverLib encodes SAMPWIN and THRESH as value-minus-one. */
    uint32_t window = ((f->cmp[0x30U / 2U] >> 3U) & 31U) + 1U;
    uint32_t threshold = ((f->cmp[0x30U / 2U] >> 9U) & 31U) + 1U;
    if (!window || !threshold || threshold > window) {
        return; /* incomplete/invalid filter cannot emit an event */
    }
    uint32_t divisor = f->cmp[0x32U / 2U] |
                       ((uint32_t)f->cmp[0x72U / 2U] << 16);
    /* Bounded ideal majority-filter delay, not analog propagation model. */
    uint64_t ns = (uint64_t)threshold * (divisor + 1U) *
                  AM13E_G10_ECAP_TICK_NS;
    timer_mod(f->filter_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
              (int64_t)ns);
}
static void am13e_g10_pwm_sync(AM13ESimFeedback *f)
{
    if (!am13e_g10_cmp_powered(f)) {
        return;
    }
    if (f->cmp[0x08U / 2U] & 0x80U) {
        f->cmp[0x0eU / 2U] = f->cmp[0x0cU / 2U];
        am13e_g10_cmp_evaluate(f);
    }
}
static void am13e_g10_reset(AM13ESimFeedback *f)
{
    if (f->overflow_timer) timer_del(f->overflow_timer);
    if (f->filter_timer) timer_del(f->filter_timer);
    f->count_base = 0U;
    f->epoch_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    memset(f->cap, 0, sizeof(f->cap));
    f->ctrphs = f->ecctl0 = f->syncsel = 0U;
    f->ecctl1 = f->ecctl2 = f->eceint = f->ecflg = 0U;
    f->capture_index = 0U;
    f->oneshot_frozen = false;
    memset(f->cmp, 0, sizeof(f->cmp));
    memset(f->phase_code, 0, sizeof(f->phase_code));
    memset(f->phase_valid, 0, sizeof(f->phase_valid));
    f->filtered = f->filter_pending = f->cmp_latch = false;
    f->caplden_ever_enabled = false;
    f->caplden_enable_transitions = 0U;
    f->reported_ecap = f->reported_cmp = false;
    am13e_g10_irq_update(f);
}
static MemTxResult am13e_g10_reject(AM13ESimFeedback *f,
                                   bool ecap, bool write,
                                   hwaddr off, unsigned size)
{
    bool *reported = ecap ? &f->reported_ecap : &f->reported_cmp;
    if (!*reported) {
        error_report("G10_UNMODELED_%s %s 0x%08" PRIx64
                     " size=%u (transaction rejected)",
                     ecap ? "ECAP1" : "CMPSS0", write ? "write" : "read",
                     (uint64_t)((ecap ? AM13E_G10_ECAP_BASE :
                                 AM13E_G10_CMPSS_BASE) + off), size);
        *reported = true;
    }
    return MEMTX_ERROR;
}
static bool am13e_g10_ecap_get16(AM13ESimFeedback *f,
                                 hwaddr off, uint16_t *v)
{
    switch (off) {
    case 0x28: *v = f->ecctl1; return true;
    case 0x2a: *v = f->ecctl2 |
                  ((uint16_t)f->capture_index << 14); return true;
    case 0x2c: *v = f->eceint; return true;
    case 0x2e: *v = f->ecflg; return true;
    case 0x30: case 0x32: *v = 0U; return true; /* W1C/W1S strobes */
    default: return false;
    }
}
static bool am13e_g10_ecap_put16(AM13ESimFeedback *f,
                                 hwaddr off, uint16_t v)
{
    switch (off) {
    case 0x28:
        /* Sticky diagnostic records the ACTUAL guest MMIO transition,
         * unlike GDB sampling at arbitrary multiples of 16 steps.
         * An independent simulator-only read-only observer exposes it;
         * there is no corresponding AM13E register or firmware write. */
        if ((v & 0x0100U) && !(f->ecctl1 & 0x0100U)) {
            f->caplden_ever_enabled = true;
            ++f->caplden_enable_transitions;
        }
        f->ecctl1 = v;
        return true;
    case 0x2a: {
        bool before = !!(f->ecctl2 & 0x10U);
        if (before) am13e_g10_stop_counter(f);
        if (v & 0x800U) {
            f->capture_index = 0U;
            f->ecflg = 0U;
            am13e_g10_irq_update(f);
        }
        if (v & 0x08U) {
            f->capture_index = 0U;
            f->oneshot_frozen = false;
        }
        if ((v & 0x100U) && (v & 0x20U)) {
            f->count_base = f->ctrphs;
        }
        /* REARM, SW_SYNC, CTRFILTRESET are self-clearing;
         * MODCNTRSTS is read-only.
         */
        f->ecctl2 = v & ~(uint16_t)0xc908U;
        if (f->ecctl2 & 0x10U) {
            am13e_g10_start_counter(f);
        }
        return true;
    }
    case 0x2c:
        f->eceint = v & AM13E_G10_ECAP_EVENT_MASK;
        if (f->ecflg & f->eceint) f->ecflg |= 1U;
        am13e_g10_irq_update(f);
        return true;
    case 0x30:
        f->ecflg &= ~(v & 0xffU);
        am13e_g10_irq_update(f);
        return true;
    case 0x32:
        am13e_g10_flags(f, v);
        return true;
    default: return false;
    }
}
static MemTxResult am13e_g10_ecap_read(void *opaque, hwaddr off,
                                        uint64_t *value, unsigned size,
                                        MemTxAttrs attrs)
{
    AM13ESimFeedback *f = opaque;
    if (!am13e_g10_ecap_powered(f)) {
        return am13e_g10_reject(f, true, false, off, size);
    }
    if (size == 4U) {
        if (off == 0U) *value = am13e_g10_count(f);
        else if (off == 4U) *value = f->ctrphs;
        else if (off >= 8U && off <= 0x14U && !(off & 3U))
            *value = f->cap[(off - 8U) / 4U];
        else if (off == 0x24U) *value = f->ecctl0;
        else if (off == 0x3cU) *value = f->syncsel;
        else if (off >= 0x28U && off <= 0x30U && !(off & 3U)) {
            uint16_t lo, hi;
            if (!am13e_g10_ecap_get16(f, off, &lo) ||
                !am13e_g10_ecap_get16(f, off + 2U, &hi)) goto bad;
            *value = lo | ((uint32_t)hi << 16);
        } else goto bad;
        return MEMTX_OK;
    }
    if (size == 2U) {
        uint16_t v;
        if (!am13e_g10_ecap_get16(f, off, &v)) goto bad;
        *value = v;
        return MEMTX_OK;
    }
bad:
    return am13e_g10_reject(f, true, false, off, size);
}
static MemTxResult am13e_g10_ecap_write(void *opaque, hwaddr off,
                                         uint64_t value, unsigned size,
                                         MemTxAttrs attrs)
{
    AM13ESimFeedback *f = opaque;
    uint32_t v = (uint32_t)value;
    if (!am13e_g10_ecap_powered(f)) {
        return am13e_g10_reject(f, true, true, off, size);
    }
    if (size == 4U) {
        if (off == 0U) {
            f->count_base = v; f->epoch_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
            am13e_g10_ovf_rearm(f);
        } else if (off == 4U) f->ctrphs = v;
        else if (off == 0x24U) f->ecctl0 = v & 0x7fU;
        else if (off == 0x3cU) f->syncsel = v;
        else if (off >= 0x28U && off <= 0x30U && !(off & 3U)) {
            if (!am13e_g10_ecap_put16(f, off, v & 0xffffU) ||
                !am13e_g10_ecap_put16(f, off + 2U, v >> 16)) goto bad;
        } else goto bad; /* CAPx are captured by events, not firmware */
        return MEMTX_OK;
    }
    if (size == 2U && am13e_g10_ecap_put16(f, off, v)) {
        return MEMTX_OK;
    }
bad:
    return am13e_g10_reject(f, true, true, off, size);
}
static const MemoryRegionOps am13e_g10_ecap_ops = {
    .read_with_attrs = am13e_g10_ecap_read,
    .write_with_attrs = am13e_g10_ecap_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 2, .max_access_size = 4 },
};

/* Valid register offsets only. All unknown subaddresses fail closed. */
static bool am13e_g10_cmp_address(hwaddr off)
{
    switch (off) {
    case 0x00: case 0x02: case 0x04: case 0x06: case 0x08:
    case 0x0c: case 0x0e: case 0x24: case 0x26: case 0x2c:
    case 0x2e: case 0x30: case 0x32: case 0x34: case 0x48:
    case 0x6e: case 0x72: return true;
    default: return false;
    }
}
static bool am13e_g10_cmp_read16(AM13ESimFeedback *f, hwaddr off,
                                  uint16_t *v)
{
    if (!am13e_g10_cmp_address(off)) return false;
    if (off == 0x04U) {
        *v = (f->filtered ? 1U : 0U) | (f->cmp_latch ? 2U : 0U);
    } else if (off == 0x06U) {
        *v = f->cmp[off / 2U] & 0x404U; /* pulse-clear fields */
    } else {
        *v = f->cmp[off / 2U];
    }
    return true;
}
static bool am13e_g10_cmp_write16(AM13ESimFeedback *f, hwaddr off,
                                   uint16_t v)
{
    if (!am13e_g10_cmp_address(off) || off == 0x04U ||
        off == 0x0eU || off == 0x26U) return false;
    if (off == 0x06U) {
        if (v & 2U) f->cmp_latch = false;
        f->cmp[off / 2U] = v & 0x404U;
        return true;
    }
    if (off == 0x0cU || off == 0x24U) {
        v &= 0x0fffU;
    }
    bool filter_init = off == 0x30U && !!(v & 0x8000U);
    if (off == 0x30U) v &= 0x7fffU; /* FILINIT self-clears */
    f->cmp[off / 2U] = v;
    if (off == 0x0cU && !(f->cmp[0x08U / 2U] & 0x80U)) {
        f->cmp[0x0eU / 2U] = v;
    }
    if (off == 0x24U) f->cmp[0x26U / 2U] = v;
    if (off == 0x08U && !(v & 0x80U)) {
        f->cmp[0x0eU / 2U] = f->cmp[0x0cU / 2U];
    }
    if (filter_init) {
        if (f->filter_timer) timer_del(f->filter_timer);
        f->filtered = am13e_g10_raw(f);
        f->filter_pending = f->filtered;
    }
    am13e_g10_cmp_evaluate(f);
    return true;
}
static MemTxResult am13e_g10_cmp_read(void *opaque, hwaddr off,
                                      uint64_t *value, unsigned size,
                                      MemTxAttrs attrs)
{
    AM13ESimFeedback *f = opaque;
    uint16_t lo, hi;
    if (!am13e_g10_cmp_powered(f)) {
        return am13e_g10_reject(f, false, false, off, size);
    }
    if (size == 2U && am13e_g10_cmp_read16(f, off, &lo)) {
        *value = lo; return MEMTX_OK;
    }
    if (size == 4U && !(off & 3U) &&
        am13e_g10_cmp_read16(f, off, &lo) &&
        am13e_g10_cmp_read16(f, off + 2U, &hi)) {
        *value = lo | ((uint32_t)hi << 16); return MEMTX_OK;
    }
    return am13e_g10_reject(f, false, false, off, size);
}
static MemTxResult am13e_g10_cmp_write(void *opaque, hwaddr off,
                                       uint64_t value, unsigned size,
                                       MemTxAttrs attrs)
{
    AM13ESimFeedback *f = opaque;
    uint32_t v = (uint32_t)value;
    if (!am13e_g10_cmp_powered(f)) {
        return am13e_g10_reject(f, false, true, off, size);
    }
    if (size == 2U && am13e_g10_cmp_write16(f, off, v)) {
        return MEMTX_OK;
    }
    if (size == 4U && !(off & 3U) &&
        am13e_g10_cmp_address(off) &&
        am13e_g10_cmp_address(off + 2U) &&
        am13e_g10_cmp_write16(f, off, v & 0xffffU) &&
        am13e_g10_cmp_write16(f, off + 2U, v >> 16)) {
        return MEMTX_OK;
    }
    return am13e_g10_reject(f, false, true, off, size);
}
static const MemoryRegionOps am13e_g10_cmp_ops = {
    .read_with_attrs = am13e_g10_cmp_read,
    .write_with_attrs = am13e_g10_cmp_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 2, .max_access_size = 4 },
};

/* Test fixture: 3 x 12-bit virtual BEMF phase sample codes. No phase
 * voltage is synthesized from PWM duty and no comparator defaults true.
 * Writes produce real threshold transitions only when the firmware route,
 * DAC, enable, power, and digital filter are all configured.
 */
static MemTxResult am13e_g10_stim_read(void *opaque, hwaddr off,
                                       uint64_t *value, unsigned size,
                                       MemTxAttrs attrs)
{
    AM13ESimFeedback *f = opaque;
    if (!f->machine->esc_sim || size != 4U ||
        off >= 16U || (off & 3U)) return MEMTX_ERROR;
    if (off == 12U) {
        /* Test-only read-only history, never a native silicon register.
         * bit0: ECCTL1.CAPLDEN has been enabled since device reset.
         * bits31:16: bounded count of actual 0->1 transitions. */
        *value = (f->caplden_ever_enabled ? 1U : 0U) |
                 (MIN(f->caplden_enable_transitions, UINT32_C(65535)) << 16);
        return MEMTX_OK;
    }
    unsigned phase = off / 4U;
    *value = f->phase_code[phase] | (f->phase_valid[phase] ? 0x10000U : 0U);
    return MEMTX_OK;
}
static MemTxResult am13e_g10_stim_write(void *opaque, hwaddr off,
                                        uint64_t value, unsigned size,
                                        MemTxAttrs attrs)
{
    AM13ESimFeedback *f = opaque;
    if (!f->machine->esc_sim || size != 4U || off >= 12U || (off & 3U) ||
        (value & ~UINT64_C(0x10fff))) return MEMTX_ERROR;
    unsigned phase = off / 4U;
    f->phase_code[phase] = value & 0xfffU;
    f->phase_valid[phase] = !!(value & 0x10000U);
    am13e_g10_cmp_evaluate(f);
    return MEMTX_OK;
}
static const MemoryRegionOps am13e_g10_stim_ops = {
    .read_with_attrs = am13e_g10_stim_read,
    .write_with_attrs = am13e_g10_stim_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};
