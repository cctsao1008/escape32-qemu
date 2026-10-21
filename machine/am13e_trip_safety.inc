/*
 * G13B2B — SIM_ONLY independent *physical* nFAULT and three-phase
 * OC/TZ shutdown plane. TI AM13E SDK: hw_xbar.h, hw_cmpss_lite.h,
 * hw_mcpwm.h. This is functional virtual safety hardware, NOT
 * production electrical qualification or comparator propagation timing.
 *
 * Crucial invariants:
 *  - No comparator signal is inferred from a nonexistent current sample.
 *    Unknown/disabled OC input is conservatively asserted if routed.
 *  - Firmware must write real INPUTXBAR/PWMXBAR/CMPSS/TZ registers.
 *  - OC/PA22 hardware input immediately latches OST2/OST3 regardless
 *    of PRIMASK. Guest W1C cannot clear a still-active fault source.
 *  - No guest UART/IRQ/throttle/PWM registers are written by simulator.
 *  - Only 3 external analog current fixture registers + one nFAULT
 *    level are synthetic; no "trip ready" shortcut exists.
 */
#define AM13E_G13B2_INPUTXBAR_BASE 0x40468000U
#define AM13E_G13B2_PWMXBAR_BASE   0x40469000U
#define AM13E_G13B2_INPUTXBAR_SIZE 0x418U
#define AM13E_G13B2_PWMXBAR_SIZE   0x150U
#define AM13E_G13B2_CMP_BASE      0x40461000U
#define AM13E_G13B2_CMP_STRIDE    0x1000U
#define AM13E_G13B2_CMP_SIZE      0x74U
#define AM13E_G13B2_SOURCE_BASE   0x5ffe5000U
#define AM13E_G13B2_TZ_OST2       (1U << 17)
#define AM13E_G13B2_TZ_OST3       (1U << 18)
#define AM13E_G13B2_INT_OST       0x04U
#define AM13E_G13B2_IN_XBAR2      1U
#define AM13E_G13B2_PW_TRIP2      1U
#define AM13E_G13B2_PW_TRIP3      2U

static bool am13e_g13b2_cmp_ready(AM13EMachineState *s, unsigned n)
{
    const AM13ETripCMP *cmp = &s->trip.cmps[n];
    const uint16_t ctrl = cmp->reg[0];
    const unsigned pin = n == 0U ? 7U : (n == 1U ? 30U : 16U);
    const uint32_t power = 1U << (n + 11U);
    /* Firmware drives analog PINCM=0 via DL_GPIO_initPeripheralAnalog...
     * The native comparator source must be DAC, DACH >0 and enabled.
     * Async CTRIPH selection 0, no fabricated latency/filter bypass.
     */
    return s->esc_sim && (s->sim_mc_power & power) &&
        (ctrl & 0x8000U) && !(ctrl & 0x0001U) &&
        (ctrl & 0x000cU) == 0U &&
        (cmp->reg[0x0e / 2U] & 0x0fffU) != 0U &&
        s->pincm[pin] == 0U &&
        s->trip.oc_valid[n];
}

static bool am13e_g13b2_cmp_trip(AM13EMachineState *s, unsigned n)
{
    AM13ETripCMP *c = &s->trip.cmps[n];
    if (!am13e_g13b2_cmp_ready(s, n)) {
        /* An unprovisioned physical current input cannot be treated as
         * a healthy overcurrent comparator: fail closed. */
        return true;
    }
    uint16_t ctrl = c->reg[0];
    uint16_t limit = c->reg[0x0e / 2U] & 0x0fffU;
    bool above = s->trip.oc_input[n] > limit;
    return above ^ !!(ctrl & 2U);
}

static bool am13e_g13b2_trip2_level(AM13EMachineState *s)
{
    AM13ETrip *t = &s->trip;
    bool selected = (t->input_pa_raw & (1U << 22)) &&
        t->input_sel[AM13E_G13B2_IN_XBAR2] == 22U &&
        !!(t->pwm_g0[AM13E_G13B2_PW_TRIP2] & (1U << 21));
    if (!selected) return false;
    const AM13EGpioPort *gpio = &s->gpio[0];
    /* A misconfigured nFAULT physical input can never be *healthy*
     * under a selected trip route in a virtual electrical board.
     * Native readbacks independently reject such IOMUX errors. */
    if (!gpio->powered || (gpio->doe & (1U << 22)) ||
        (s->pincm[22] & 0x000400bfU) != 0x00040081U) {
        return true;
    }
    bool raw_level = !gpio->nfault_asserted;
    bool invert = !!(t->pwm_invert & (1U << AM13E_G13B2_PW_TRIP2));
    return raw_level ^ invert;
}

static bool am13e_g13b2_trip3_level(AM13EMachineState *s)
{
    AM13ETrip *t = &s->trip;
    if (!(t->pwm_g0[AM13E_G13B2_PW_TRIP3] & 0x54U)) {
        return false;
    }
    bool t3 = false;
    for (unsigned i = 0; i < 3U; ++i) {
        if (t->pwm_g0[AM13E_G13B2_PW_TRIP3] & (1U << (2U + i * 2U))) {
            t3 |= am13e_g13b2_cmp_trip(s, i);
        }
    }
    return t3 ^ !!(t->pwm_invert & (1U << AM13E_G13B2_PW_TRIP3));
}

static void am13e_g13b2_trip_update(AM13EMachineState *s)
{
    if (!s->esc_sim) return;
    AM13ESimPWM *p = &s->pwm4;
    uint32_t sel = p->reg[0xa0U / 4U];
    uint32_t new_ost = 0U;
    if ((sel & AM13E_G13B2_TZ_OST2) && am13e_g13b2_trip2_level(s)) {
        new_ost |= AM13E_G13B2_TZ_OST2;
    }
    if ((sel & AM13E_G13B2_TZ_OST3) && am13e_g13b2_trip3_level(s)) {
        new_ost |= AM13E_G13B2_TZ_OST3;
    }
    if (new_ost) {
        /* Latch until software W1C and underlying source released. */
        p->reg[0xb0U / 4U] |= new_ost;
        p->irqs |= AM13E_G13B2_INT_OST;
        am13e_pwm4_irq_update(p);
    }
}

static void am13e_g13b2_reset(AM13EMachineState *s)
{
    AM13ETrip *t = &s->trip;
    memset(t->input_sel, 0, sizeof(t->input_sel));
    t->input_pa_raw = 0U;
    memset(t->pwm_g0, 0, sizeof(t->pwm_g0));
    memset(t->pwm_g1, 0, sizeof(t->pwm_g1));
    t->pwm_invert = 0U;
    for (unsigned i = 0; i < 3U; ++i) {
        memset(t->cmps[i].reg, 0, sizeof(t->cmps[i].reg));
        t->oc_input[i] = 0U;
        t->oc_valid[i] = false;  /* no silent healthy analog assumption */
    }
}

static MemTxResult am13e_g13b2_xbar_read(void *opaque, hwaddr off,
                                         uint64_t *value, unsigned size,
                                         MemTxAttrs attrs)
{
    AM13ETrip *t = opaque;
    if (!t->machine->esc_sim || size != 4U || (off & 3U)) return MEMTX_ERROR;
    if (attrs.requester_id == 0xffff) { /* no special bypass */ }
    /* Same callbacks operate on separate MemoryRegions. Disambiguate by
     * the base through two tiny wrappers defined below instead. */
    return MEMTX_ERROR;
}
static MemTxResult am13e_g13b2_input_read(void *opaque, hwaddr off,
                                          uint64_t *val, unsigned size,
                                          MemTxAttrs attrs)
{
    AM13ETrip *t = opaque;
    if (!t->machine->esc_sim || size != 4U || (off & 3U)) return MEMTX_ERROR;
    if (off == 0x04U) { *val = t->input_sel[1]; return MEMTX_OK; }
    if (off == 0x410U) { *val = t->input_pa_raw; return MEMTX_OK; }
    return MEMTX_ERROR;
}
static MemTxResult am13e_g13b2_input_write(void *opaque, hwaddr off,
                                           uint64_t value, unsigned size,
                                           MemTxAttrs attrs)
{
    AM13ETrip *t = opaque;
    if (!t->machine->esc_sim || size != 4U || (off & 3U) ||
        (value >> 32)) return MEMTX_ERROR;
    if (off == 0x04U && value <= 255U) {
        t->input_sel[1] = (uint32_t)value;
    } else if (off == 0x410U && !(value & ~(UINT64_C(1) << 22))) {
        t->input_pa_raw = (uint32_t)value;
    } else {
        return MEMTX_ERROR;
    }
    am13e_g13b2_trip_update(t->machine);
    return MEMTX_OK;
}
static const MemoryRegionOps am13e_g13b2_input_ops = {
    .read_with_attrs=am13e_g13b2_input_read,
    .write_with_attrs=am13e_g13b2_input_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4},
};

static MemTxResult am13e_g13b2_pwm_xbar_read(void *opaque, hwaddr off,
                                             uint64_t *val, unsigned size,
                                             MemTxAttrs attrs)
{
    AM13ETrip *t = opaque;
    if (!t->machine->esc_sim || size != 4U || (off & 3U)) return MEMTX_ERROR;
    if (off == 0x30U) { *val = t->pwm_invert; return MEMTX_OK; }
    for (unsigned i = 1U; i <= 2U; ++i) {
        if (off == 0x100U + 8U * i) {
            *val = t->pwm_g0[i]; return MEMTX_OK;
        }
        if (off == 0x104U + 8U * i) {
            *val = t->pwm_g1[i]; return MEMTX_OK;
        }
    }
    return MEMTX_ERROR;
}
static MemTxResult am13e_g13b2_pwm_xbar_write(void *opaque, hwaddr off,
                                              uint64_t value, unsigned size,
                                              MemTxAttrs attrs)
{
    AM13ETrip *t = opaque;
    if (!t->machine->esc_sim || size != 4U || (off & 3U) ||
        (value >> 32)) return MEMTX_ERROR;
    uint32_t v = (uint32_t)value;
    if (off == 0x30U && !(v & ~0x06U)) {
        t->pwm_invert = v;
    } else {
        bool found = false;
        for (unsigned i = 1U; i <= 2U; ++i) {
            if (off == 0x100U + 8U * i && !(v & ~(i == 1U ? 0x00200000U : 0x54U))) {
                t->pwm_g0[i] = v; found = true; break;
            }
            if (off == 0x104U + 8U * i && v == 0U) {
                t->pwm_g1[i] = 0U; found = true; break;
            }
        }
        if (!found) return MEMTX_ERROR;
    }
    am13e_g13b2_trip_update(t->machine);
    return MEMTX_OK;
}
static const MemoryRegionOps am13e_g13b2_pwm_xbar_ops = {
    .read_with_attrs=am13e_g13b2_pwm_xbar_read,
    .write_with_attrs=am13e_g13b2_pwm_xbar_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4},
};

static bool am13e_g13b2_cmp_offset(hwaddr off)
{
    switch (off) {
    case 0x00U: case 0x04U: case 0x06U: case 0x08U:
    case 0x0cU: case 0x0eU: case 0x24U: case 0x26U:
        return true;
    default: return false;
    }
}
static MemTxResult am13e_g13b2_cmp_read(void *opaque, hwaddr off,
                                        uint64_t *val, unsigned size,
                                        MemTxAttrs attrs)
{
    AM13ETripCMP *c = opaque;
    AM13ETrip *t = c->trip;
    if (!t->machine->esc_sim || size != 2U || (off & 1U) ||
        !am13e_g13b2_cmp_offset(off)) return MEMTX_ERROR;
    if (!(t->machine->sim_mc_power & (1U << (c->index + 11U))))
        return MEMTX_ERROR;
    if (off == 0x04U) {
        bool raw = am13e_g13b2_cmp_trip(t->machine, c->index);
        *val = (raw ? 1U : 0U) | (raw ? 2U : 0U);
        return MEMTX_OK;
    }
    if (off == 0x06U) { *val = 0; return MEMTX_OK; }
    *val = c->reg[off / 2U];
    return MEMTX_OK;
}
static MemTxResult am13e_g13b2_cmp_write(void *opaque, hwaddr off,
                                         uint64_t value, unsigned size,
                                         MemTxAttrs attrs)
{
    AM13ETripCMP *c = opaque;
    AM13ETrip *t = c->trip;
    if (!t->machine->esc_sim || size != 2U || (off & 1U) ||
        value > 0xffffU || !am13e_g13b2_cmp_offset(off) ||
        !(t->machine->sim_mc_power & (1U << (c->index + 11U))))
        return MEMTX_ERROR;
    if (off == 0x04U || off == 0x0eU || off == 0x26U)
        return MEMTX_ERROR; /* status, active DAC are RO */
    if (off == 0x06U) {
        /* No direct software forcing of a false healthy raw comparator. */
        return value == 0U ? MEMTX_OK : MEMTX_ERROR;
    }
    c->reg[off / 2U] = (uint16_t)value;
    if (off == 0x0cU) {
        c->reg[0x0eU / 2U] = (uint16_t)value & 0x0fffU;
    }
    if (off == 0x24U) {
        c->reg[0x26U / 2U] = (uint16_t)value & 0x0fffU;
    }
    am13e_g13b2_trip_update(t->machine);
    return MEMTX_OK;
}
static const MemoryRegionOps am13e_g13b2_cmp_ops = {
    .read_with_attrs=am13e_g13b2_cmp_read,
    .write_with_attrs=am13e_g13b2_cmp_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=2,.max_access_size=2},
};

/* External currents are explicit *analog samples*, not comparator or
 * IRQ flags. OC sample is 12-bit current amplifier output code.
 * No sample = unsafe when the OC route is selected. */
static MemTxResult am13e_g13b2_stim_read(void *opaque, hwaddr off,
                                         uint64_t *val, unsigned size,
                                         MemTxAttrs attrs)
{
    AM13ETrip *t = opaque;
    if (!t->machine->esc_sim || size != 4U || (off & 3U)) return MEMTX_ERROR;
    if (off < 12U) {
        unsigned n = off / 4U;
        *val = (t->oc_valid[n] ? 0x10000U : 0U) | t->oc_input[n];
        return MEMTX_OK;
    }
    if (off == 0x10U) {
        *val = (am13e_g13b2_trip2_level(t->machine) ? 2U : 0U) |
               (am13e_g13b2_trip3_level(t->machine) ? 4U : 0U);
        return MEMTX_OK;
    }
    if (off == 0x14U) {
        *val = t->machine->pwm4.reg[0xb0U / 4U] &
               (AM13E_G13B2_TZ_OST2 | AM13E_G13B2_TZ_OST3);
        return MEMTX_OK;
    }
    if (off == 0x18U) {
        *val = t->machine->gpio[0].nfault_asserted ? 1U : 0U;
        return MEMTX_OK;
    }
    return MEMTX_ERROR;
}
static MemTxResult am13e_g13b2_stim_write(void *opaque, hwaddr off,
                                          uint64_t value, unsigned size,
                                          MemTxAttrs attrs)
{
    AM13ETrip *t = opaque;
    if (!t->machine->esc_sim || size != 4U || (off & 3U) ||
        (value >> 32)) return MEMTX_ERROR;
    if (off < 12U) {
        unsigned n = off / 4U;
        /* Bit16 establishes validity, bits11:0 are physical ADC code.
         * Writing zero without VALID clears rather than forging 'safe'. */
        if (value & ~UINT64_C(0x10fff)) return MEMTX_ERROR;
        t->oc_input[n] = (uint16_t)value & 0x0fffU;
        t->oc_valid[n] = !!(value & 0x10000U);
    } else if (off == 0x18U && value <= 1U) {
        t->machine->gpio[0].nfault_asserted = value != 0U;
    } else {
        return MEMTX_ERROR;
    }
    am13e_g13b2_trip_update(t->machine);
    return MEMTX_OK;
}
static const MemoryRegionOps am13e_g13b2_stim_ops = {
    .read_with_attrs=am13e_g13b2_stim_read,
    .write_with_attrs=am13e_g13b2_stim_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4},
};
