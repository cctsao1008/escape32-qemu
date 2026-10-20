/*
 * G13B1: simulator-only, bounded external PA26 waveform scheduler.
 *
 * External physical line transitions only. The guest's real PA26 PINCM,
 * TIMG4 CCP0, GEN_EVENT1 and DMA0 CH2 must be configured and powered
 * before a scheduled edge can become a captured timestamp. No command
 * decode, no firmware SRAM patch, no IRQ/edge flag injection.
 *
 * 0x5ffe4000 non-silicon test-control port, 32-bit aligned only:
 *  WRITE +0 delay_ns [10..100000000], +4 level [0..1]
 *  WRITE +0x18 1 to enqueue the staged physical edge (<=256)
 *  WRITE +0x1c 1 to play from QEMU virtual time
 *  WRITE +0x20 1 to clear only when idle
 *  READ +0x08 count, +0x0c delivered, +0x10 busy, +0x14 line level.
 */
#define AM13E_PA26_WAVE_BASE 0x5ffe4000U
#define AM13E_PA26_WAVE_SIZE 0x24U
#define AM13E_PA26_WAVE_LIMIT 256U

static void am13e_pa26_wave_reset(AM13EPA26Wave *w)
{
    if (w->timer) {
        timer_del(w->timer);
    }
    w->staged_delay = w->staged_level = 0U;
    w->queued = w->delivered = 0U;
    w->delay_valid = w->level_valid = w->running = false;
}

static void am13e_pa26_wave_event(void *opaque)
{
    AM13EPA26Wave *w = opaque;
    if (!w->running || w->delivered >= w->queued) {
        return;
    }
    unsigned n = w->delivered;
    /* Reuse G7B's original PA26 edge handler. Only the real PINCM,
     * timer-capture and DMA wiring can publish a guest timestamp. */
    if (am13e_sim_pa26_write(w->machine, 0U, w->levels[n], 4U,
                            MEMTXATTRS_UNSPECIFIED) != MEMTX_OK) {
        w->running = false;
        error_report("G13B1_PA26_WAVE_PHYSICAL_EDGE_REJECTED index=%u", n);
        return;
    }
    w->delivered++;
    if (w->delivered >= w->queued) {
        w->running = false;
        return;
    }
    timer_mod(w->timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
              w->delta_ns[w->delivered]);
}

static MemTxResult am13e_pa26_wave_read(void *opaque, hwaddr off,
                                        uint64_t *val, unsigned size,
                                        MemTxAttrs attrs)
{
    AM13EPA26Wave *w = opaque;
    if (!w->machine->esc_sim || size != 4U || (off & 3U)) {
        return MEMTX_ERROR;
    }
    switch (off) {
    case 0x08: *val = w->queued; return MEMTX_OK;
    case 0x0c: *val = w->delivered; return MEMTX_OK;
    case 0x10: *val = w->running ? 1U : 0U; return MEMTX_OK;
    case 0x14: *val = w->machine->sim_pa26_level; return MEMTX_OK;
    default: return MEMTX_ERROR;
    }
}

static MemTxResult am13e_pa26_wave_write(void *opaque, hwaddr off,
                                         uint64_t value, unsigned size,
                                         MemTxAttrs attrs)
{
    AM13EPA26Wave *w = opaque;
    uint32_t v = (uint32_t)value;
    if (!w->machine->esc_sim || size != 4U || (off & 3U) ||
        value != (uint64_t)v) {
        return MEMTX_ERROR;
    }
    switch (off) {
    case 0x00:
        if (w->running || v < 10U || v > 100000000U) {
            return MEMTX_ERROR;
        }
        w->staged_delay = v;
        w->delay_valid = true;
        return MEMTX_OK;
    case 0x04:
        if (w->running || v > 1U) {
            return MEMTX_ERROR;
        }
        w->staged_level = v;
        w->level_valid = true;
        return MEMTX_OK;
    case 0x18:
        if (v != 1U || w->running ||
            w->queued >= AM13E_PA26_WAVE_LIMIT ||
            !w->delay_valid || !w->level_valid) {
            return MEMTX_ERROR;
        }
        w->delta_ns[w->queued] = w->staged_delay;
        w->levels[w->queued] = w->staged_level;
        w->queued++;
        w->delay_valid = w->level_valid = false;
        return MEMTX_OK;
    case 0x1c:
        if (v != 1U || w->running || !w->queued || w->delivered) {
            return MEMTX_ERROR;
        }
        w->running = true;
        timer_mod(w->timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
                  w->delta_ns[0]);
        return MEMTX_OK;
    case 0x20:
        if (v != 1U || w->running) {
            return MEMTX_ERROR;
        }
        am13e_pa26_wave_reset(w);
        return MEMTX_OK;
    default:
        return MEMTX_ERROR;
    }
}

static const MemoryRegionOps am13e_pa26_wave_ops = {
    .read_with_attrs = am13e_pa26_wave_read,
    .write_with_attrs = am13e_pa26_wave_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};
