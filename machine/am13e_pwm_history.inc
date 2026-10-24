/*
 * G13B3 Historical QEMU MCPWM4 INTERNAL logic transitions, ESC-SIM only.
 *
 * This is a separate virtual-clock callback JOURNAL. Unlike the one-carrier
 * plan, records exist only after actual QEMU timer callbacks/Guest MMIO
 * transitions. They are NOT measured MOSFET/pin/driver/deadtime waveforms.
 *
 * The edge_timer is observer-only. It never changes Guest PWM/IRQ/ADC/ECAP,
 * original zero_timer scheduling, motor dynamics or plant feedback.
 * A 128-entry overwrite ring is deliberately lossy; the host sees DROPPED
 * and must never claim full provenance after the ring has wrapped.
 *
 * This helper is included after am13e_pwm4_switch_mask(), while its
 * forward declarations are above am13e_trip_safety.inc.
 */
#define AM13E_H_MAGIC 0x48323645U  /* E62H */

static uint32_t am13e_pwm4_hist_gate_word(AM13ESimPWM *p)
{
    /* GPIO1 PB13 raw state + routing only; active polarity is a separate
     * original-board property, and driver/fault propagation is unknown.
     * bit0 raw high; bit1 DOE; bit2 GPIO powered; bit3 PB13 PINCM good.
     */
    AM13EMachineState *s = p->machine;
    const AM13EGpioPort *g = &s->gpio[1];
    return (!!(g->dout & (1U << 13U))) |
           ((!!(g->doe & (1U << 13U))) << 1U) |
           ((!!g->powered) << 2U) |
           (((s->pincm[45] & 0xbfU) == 0x81U) << 3U);
}

static void am13e_pwm4_hist_log(AM13ESimPWM *p, uint32_t kind,
                                uint32_t oldmask, uint32_t newmask,
                                uint32_t ctr, bool valid)
{
    if (!p->machine->esc_sim) {
        return;
    }
    uint64_t seq = p->hist_total;
    unsigned slot = (unsigned)(seq % AM13E_H_CAPACITY);
    AM13EPWMHistoryRecord *r = &p->hist_records[slot];
    r->time_ns = (uint64_t)qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    r->type = kind;
    r->oldmask = oldmask & 0x3fU;
    r->newmask = newmask & 0x3fU;
    r->counter = ctr;
    r->zero = p->zero_events;
    r->aux = (am13e_pwm4_hist_gate_word(p) & 0xffU) |
             ((p->reg[0xb0U / 4U] & 0x60000U) >> 8U) |
             (valid ? 0x10000U : 0U);
    p->hist_total++;
    if (p->hist_total > AM13E_H_CAPACITY) {
        p->hist_dropped++;
    }
    p->hist_last_time_ns = r->time_ns;
}

/* Candidate ticks are the only instants where the *existing*
 * am13e_pwm4_level() could change within a static up-counting carrier:
 * CA/CB, delayed CA/CB, or delayed ZERO. Evaluate before/after each
 * candidate using the ORIGINAL output-level function. Unsupported
 * AQ/DB will not be interpreted as physically valid transitions.
 */
static bool am13e_pwm4_hist_next_tick(AM13ESimPWM *p, uint32_t from,
                                      uint32_t *found)
{
    uint32_t period = p->reg[0x14U / 4U] & 0xffffU;
    uint32_t total = period + 1U;
    uint32_t earliest = total;
    if (!p->running || !am13e_pwm4_clock_allowed(p) || !period) {
        return false;
    }
    bool valid = true;
    for (unsigned out = 0U; out < 6U; ++out) {
        uint32_t base = 0x100U + (out / 2U) * 0x200U;
        uint32_t ca = p->reg[(base + 0x00U) / 4U];
        uint32_t cb = p->reg[(base + 0x08U) / 4U];
        uint32_t ctl = p->reg[0xc0U / 4U];
        uint32_t dly = (out & 1U) ?
            ((ctl & 2U) ? (p->reg[0xd0U / 4U] & 0x3fffU) : 0U) :
            ((ctl & 1U) ? (p->reg[0xd4U / 4U] & 0x3fffU) : 0U);
        uint32_t candidates[5] = {
            ca, cb, dly,
            (ca + dly) % total,
            (cb + dly) % total,
        };
        for (unsigned k = 0; k < 5U; ++k) {
            uint32_t c = candidates[k];
            if (!c || c >= total || c <= from || c >= earliest) {
                continue;
            }
            uint32_t previous = am13e_pwm4_switch_mask(p,c-1U,&valid);
            uint32_t current = am13e_pwm4_switch_mask(p,c,&valid);
            if (!valid) {
                return false;
            }
            if (previous != current) {
                earliest = c;
            }
        }
    }
    if (!valid || earliest >= total) {
        return false;
    }
    *found = earliest;
    return true;
}

static void am13e_pwm4_hist_schedule(AM13ESimPWM *p)
{
    if (p->edge_timer) {
        timer_del(p->edge_timer);
    }
    if (!p->running || !am13e_pwm4_clock_allowed(p) ||
        !p->hist_model_valid || !p->edge_timer) {
        return;
    }
    uint32_t now_ctr = am13e_pwm4_count(p);
    uint32_t target = 0U;
    if (!am13e_pwm4_hist_next_tick(p,now_ctr,&target)) {
        return;
    }
    uint32_t hz = am13e_pwm4_hz(p);
    uint32_t base = p->counter_base %
        ((p->reg[0x14U / 4U] & 0xffffU) + 1U);
    if (!hz || target <= base) {
        return;  /* May have reset counter mid-carrier; no prediction. */
    }
    uint64_t offset = ((uint64_t)(target-base) * UINT64_C(1000000000)
                       + hz-1U) / hz;
    int64_t deadline = p->epoch_ns + (int64_t)offset;
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    if (deadline <= now) {
        /* Never invent earlier edges at "now" after a late callback.
         * A scheduled historic edge must be strictly future-dated.
         */
        p->hist_model_valid = false;
        p->hist_invalid_count++;
        am13e_pwm4_hist_log(p,AM13E_H_INVALID,p->hist_mask,
                            p->hist_mask,now_ctr,false);
        return;
    }
    timer_mod(p->edge_timer,deadline);
}

/* Read old mask from the PREVIOUS clocked state, not from current
 * registers interpreted retroactively. Called at PWM MMIO boundaries,
 * virtual ZERO/shadow, clock transitions and Trip changes.
 */
static void am13e_pwm4_hist_refresh(AM13ESimPWM *p, uint32_t kind,
                                     bool force)
{
    if (!p->edge_timer) {
        return;
    }
    timer_del(p->edge_timer);
    uint32_t c = am13e_pwm4_count(p);
    bool valid = true;
    uint32_t mask = am13e_pwm4_switch_mask(p,c,&valid);
    uint32_t previous = p->hist_mask;
    if (!valid) {
        if (p->hist_model_valid) {
            p->hist_invalid_count++;
            am13e_pwm4_hist_log(p,AM13E_H_INVALID,previous,
                                previous,c,false);
        }
        p->hist_model_valid = false;
        return;
    }
    if (force || mask != previous || !p->hist_model_valid) {
        am13e_pwm4_hist_log(p,kind,previous,mask,c,true);
    }
    p->hist_mask=mask;
    p->hist_model_valid=true;
    am13e_pwm4_hist_schedule(p);
}

static void am13e_pwm4_hist_edge_event(void *opaque)
{
    AM13ESimPWM *p = opaque;
    /* Only a timer callback in QEMU virtual time records an EDGE.
     * Active AQ changes use GUEST_REG, never retroactive EDGE events.
     */
    am13e_pwm4_hist_refresh(p,AM13E_H_EDGE,false);
}

static void am13e_pwm4_hist_gate(AM13ESimPWM *p)
{
    uint32_t now = am13e_pwm4_hist_gate_word(p);
    if (now != p->hist_gate_word) {
        /* Raw GPIO/PINCM observation, NOT output-driver gate assertion. */
        am13e_pwm4_hist_log(p,AM13E_H_GATE,p->hist_mask,p->hist_mask,
                            am13e_pwm4_count(p),p->hist_model_valid);
        p->hist_gate_word=now;
    }
}

/* Bounded read-only non-silicon QEMU observer:
 * base 0x5FFE7000, length 0x1000
 * 00 magic, 04 flags, 08 ABI, 0c capacity, 10 count
 * 14 total lo, 18 total hi, 1c dropped lo, 20 dropped hi
 * 24 active internal mask, 28 zero events, 2c counter,
 * 30 last record ns low, 34 last record ns high,
 * 38 hz, 3c record width in dwords, 40 invalid count
 * Records 0x80 + index*32, oldest retained first:
 * 00 t ns low,04 t ns high,08 event type,0c old mask,
 * 10 new mask,14 native counter,18 zero-event count,1c aux.
 *
 * QTest/host reads do not dequeue, clear or acknowledge. When dropped>0,
 * the list is only a recent bounded suffix of the actual callback log.
 */
static MemTxResult am13e_pwm4_hist_read(void *opaque,hwaddr off,
                                       uint64_t *val,unsigned size,
                                       MemTxAttrs attrs)
{
    AM13ESimPWM *p=opaque;
    if (!p->machine->esc_sim || size!=4U || (off&3U) ||
        off>=AM13E_SIM_PWM_HIST_SIZE) {
        return MEMTX_ERROR;
    }
    uint64_t total=p->hist_total, dropped=p->hist_dropped;
    uint32_t count=(uint32_t)MIN(total,(uint64_t)AM13E_H_CAPACITY);
    switch (off) {
    case 0x00U: *val=AM13E_H_MAGIC;return MEMTX_OK;
    case 0x04U:
        *val=(p->running?1U:0U) |
             (p->hist_model_valid?2U:0U) |
             (dropped?4U:0U) |
             8U; /* Actual QEMU virtual-clock callback/Guest MMIO journal */
        return MEMTX_OK;
    case 0x08U:*val=1U;return MEMTX_OK;
    case 0x0cU:*val=AM13E_H_CAPACITY;return MEMTX_OK;
    case 0x10U:*val=count;return MEMTX_OK;
    case 0x14U:*val=(uint32_t)total;return MEMTX_OK;
    case 0x18U:*val=total>>32;return MEMTX_OK;
    case 0x1cU:*val=(uint32_t)dropped;return MEMTX_OK;
    case 0x20U:*val=dropped>>32;return MEMTX_OK;
    case 0x24U:*val=p->hist_mask;return MEMTX_OK;
    case 0x28U:*val=p->zero_events;return MEMTX_OK;
    case 0x2cU:*val=am13e_pwm4_count(p);return MEMTX_OK;
    case 0x30U:*val=(uint32_t)p->hist_last_time_ns;return MEMTX_OK;
    case 0x34U:*val=p->hist_last_time_ns>>32;return MEMTX_OK;
    case 0x38U:*val=am13e_pwm4_hz(p);return MEMTX_OK;
    case 0x3cU:*val=AM13E_H_REC_WORDS;return MEMTX_OK;
    case 0x40U:*val=p->hist_invalid_count;return MEMTX_OK;
    default:
        if (off<0x80U) {
            return MEMTX_ERROR;
        }
        unsigned index=(off-0x80U)/(AM13E_H_REC_WORDS*4U);
        if (index>=count) {
            return MEMTX_ERROR;
        }
        /* Logical index 0 = oldest currently retained record. */
        uint64_t sequence = total-count+index;
        const AM13EPWMHistoryRecord *r =
            &p->hist_records[sequence%AM13E_H_CAPACITY];
        switch (((off-0x80U)/4U)%AM13E_H_REC_WORDS) {
        case 0:*val=(uint32_t)r->time_ns;return MEMTX_OK;
        case 1:*val=r->time_ns>>32;return MEMTX_OK;
        case 2:*val=r->type;return MEMTX_OK;
        case 3:*val=r->oldmask;return MEMTX_OK;
        case 4:*val=r->newmask;return MEMTX_OK;
        case 5:*val=r->counter;return MEMTX_OK;
        case 6:*val=r->zero;return MEMTX_OK;
        case 7:*val=r->aux;return MEMTX_OK;
        default: return MEMTX_ERROR;
        }
    }
}

static MemTxResult am13e_pwm4_hist_write(void *opaque,hwaddr off,
                                        uint64_t value,unsigned size,
                                        MemTxAttrs attrs)
{
    return MEMTX_ERROR;
}
static const MemoryRegionOps am13e_pwm4_hist_ops={
    .read_with_attrs=am13e_pwm4_hist_read,
    .write_with_attrs=am13e_pwm4_hist_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4},
};
