/*
 * AM13E23019 G0/G1 APP-handoff machine for QEMU v6.2.0.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "qemu/osdep.h"
#include "qemu/units.h"
#include "qemu/module.h"
#include "qapi/error.h"
#include "qemu/error-report.h"
#include "hw/arm/armv7m.h"
#include "hw/arm/boot.h"
#include "hw/boards.h"
#include "hw/qdev-clock.h"
#include "hw/qdev-properties.h"
#include "exec/address-spaces.h"
#include "qom/object.h"
#include "sysemu/reset.h"
#include "qemu/timer.h"

#define TYPE_AM13E_MACHINE MACHINE_TYPE_NAME("am13e23019")
OBJECT_DECLARE_SIMPLE_TYPE(AM13EMachineState, AM13E_MACHINE)
#define AM13E_SRAM_SIZE (128 * KiB)
#define AM13E_FLASH_SIZE (512 * KiB)
#define AM13E_APP_BASE 0x00006000U

/* TI SDK hw_memmap.h: SYSCTL_BASE=0x400AF000.
 * TI TRM SPRUJF2B §3.14.2.12 MCLKCFG reset: 07XXX2X0h.
 * §3.14.2.34 CLKSTATUS: SYSPLLOFF/HFCLKOFF/HSCLKSOFF reset 1.
 * X-designated reserved bits are deliberately represented as 0 and
 * do not constitute a claim about silicon's unspecified read values.
 */
#define AM13E_SYSCTL_BASE 0x400AF000U
#define AM13E_SYSCTL_SIZE 0x4000U
#define AM13E_SYSCTL_MCLKCFG 0x1104U
#define AM13E_SYSCTL_CLKSTATUS 0x1204U
#define AM13E_SYSCTL_MCLKCFG_INITIAL 0x07000200U
#define AM13E_SYSCTL_CLKSTATUS_INITIAL 0x00007000U

/* TRM 3.14.2.12: MCLKDIVCFG at MCLKCFG[26:24].
 * TI DriverLib DL_SYSCTL_setMCLKDivider() uses an RMW on this field.
 * Clock-source selection remains unimplemented in G2c.
 */
#define AM13E_SYSCTL_MCLKDIVCFG_MASK 0x07000000U

/* TI TRM SPRUJF2B §3.14.2.73: SYSCTL.XTALCR offset 0x1474.
 * Reset 0x00000001: OSCOFF=1 (powered down), SE=0 (crystal mode).
 * G2d models configuration bits, NOT oscillator startup completion.
 */
#define AM13E_SYSCTL_XTALCR 0x1474U
#define AM13E_SYSCTL_XTALCR_INITIAL 0x00000001U
#define AM13E_SYSCTL_XTALCR_WRITABLE 0x00000003U

/* TRM SPRUJF2B §3.14.2.13 / TI SDK hw_sysctl.h:
 * SYSCTL.HSCLKEN reset=0000XXXXh. The documented bits reset to 0;
 * undefined reserved bits are represented by 0 only in this emulator.
 * USEEXTHFCLK[16] and SYSPLLEN[8] are control requests, not GOOD status.
 */
#define AM13E_SYSCTL_HSCLKEN 0x1108U
#define AM13E_SYSCTL_HSCLKEN_INITIAL 0x00000000U
#define AM13E_SYSCTL_HSCLKEN_FIELDS 0x00010100U

/* TI TRM SPRUJF2B §3.14.2.15: SYSCTL.HFCLKCLKCFG at 0x1110.
 * Reset 1XXXXX00h: HFCLKFLTCHK[28] = 1, XTALTIME[7:0] = 0.
 * SDK DL_SYSCTL_setXTALStartupTime uses bits 7:0; the startup
 * monitor RMW uses bit 28. These are settings, not a GOOD state.
 * Unknown reserved reset bits are represented as 0 in the emulator.
 */
#define AM13E_SYSCTL_HFCLKCLKCFG 0x1110U
#define AM13E_SYSCTL_HFCLKCLKCFG_INITIAL 0x10000000U
#define AM13E_SYSCTL_HFCLKCLKCFG_FIELDS 0x100000ffU

/* TRM SPRUJF2B §§3.14.2.16–17. The X portions of the reset
 * patterns are unknown; represented as zero only for this emulator.
 * CFG0 known reset: ENABLECLK0=1, ENABLECLK1=1.
 * CFG1 known reset: QDIV=0x23, PDIV=0.
 */
#define AM13E_SYSCTL_SYSPLLCFG0 0x1120U
#define AM13E_SYSCTL_SYSPLLCFG1 0x1124U
#define AM13E_SYSCTL_SYSPLLCFG0_INITIAL 0x00000030U
#define AM13E_SYSCTL_SYSPLLCFG1_INITIAL 0x00002300U
#define AM13E_SYSCTL_SYSPLLCFG0_FIELDS 0x0000ff31U
#define AM13E_SYSCTL_SYSPLLCFG1_FIELDS 0x00007f03U

/* TI TRM SPRUJF2B §§3.14.2.18–19, SYSPLL factory tuning
 * parameter registers. Reserved R/W-X bits have undefined reset
 * values: their emulator reset image is 0, but full-word writes
 * remain opaque to preserve original firmware's FACTORY copy.
 */
#define AM13E_SYSCTL_SYSPLLPARAM0 0x1128U
#define AM13E_SYSCTL_SYSPLLPARAM1 0x112cU
#define AM13E_SYSCTL_SYSPLLPARAM0_INITIAL 0x810a0000U
#define AM13E_SYSCTL_SYSPLLPARAM1_INITIAL 0x0f00010fU
#define AM13E_SYSPLL_ENABLE (1U << 8)
#define AM13E_SIM_HSCLKCFG 0x110cU
#define AM13E_SIM_PLL_NS INT64_C(50000) /* functional sim delay, not TI lock time */
#define AM13E_SIM_PLLGOOD (1U << 9)
#define AM13E_SIM_HSCLKGOOD (1U << 21)
#define AM13E_SIM_SYSPLLOFF (1U << 14)
#define AM13E_SIM_HSCLKMUX (1U << 4)

/* TI hw_factoryregion.h and TRM §3.16: FACTORY FLASH window.
 * Only the 8–16MHz SYSPLL loop parameter pair is surfaced by G2i.
 * The two *device-programmed* words are NOT specified by SDK.
 */
#define AM13E_FACTORY_BASE 0x60111000U
#define AM13E_FACTORY_SIZE 0x80U
#define AM13E_FACTORY_PLL0_OFFSET 0x28U
#define AM13E_FACTORY_PLL1_OFFSET 0x2cU
/* Clock readiness is an event, never simply the result of writing XTALCR. */
#define AM13E_HFCLK_GOOD (1U << 8)
#define AM13E_HFCLK_OFF (1U << 13)
#define AM13E_HSCLK_OFF (1U << 12)
#define AM13E_XTAL_STARTUP_NS_PER_UNIT INT64_C(64000)

/* TI SDK hw_memmap.h / hw_fri.h and TRM SPRUJF2B §13.7.2.1:
 * FRI_BASE=0x40028000; FRDCNTL offset=0x1000, reset=0x02000201.
 * WS0_MODE bit0, RWAIT bits11:8. Preserve the undocumented RW
 * reserved [27:24] bits at their reset value; do not invent semantics.
 */
#define AM13E_FRI_BASE 0x40028000U
#define AM13E_FRI_SIZE 0x2000U
#define AM13E_FRI_FRDCNTL 0x1000U
#define AM13E_FRI_FRDCNTL_RESET 0x02000201U
#define AM13E_FRI_FRDCNTL_FIELDS (0x00000f00U | 0x00000001U)

/* TI AM13E230x SDK hw_memmap.h/hw_gpio.h:
 * GPIO0-3 at 0x400F0000 + 0x2000*n.
 * GPRCM.PWREN uses KEY=0x26[31:24] and ENABLE[0].
 * GPRCM.RSTCTL uses KEY=0xB1[31:24].
 * This is digital MMIO bring-up only; no IOMUX or DShot waveform yet.
 */
#define AM13E_GPIO_COUNT 4U
#define AM13E_GPIO_BASE 0x400F0000U
#define AM13E_GPIO_STRIDE 0x2000U
#define AM13E_GPIO_SIZE 0x2000U
#define AM13E_GPIO_PWREN 0x0800U
#define AM13E_GPIO_RSTCTL 0x0804U
#define AM13E_GPIO_STAT 0x0814U
#define AM13E_GPIO_DOUT 0x1280U
#define AM13E_GPIO_DOUTSET 0x1290U
#define AM13E_GPIO_DOUTCLR 0x12a0U
#define AM13E_GPIO_DOUTTGL 0x12b0U
#define AM13E_GPIO_DOE 0x12c0U
#define AM13E_GPIO_DOESET 0x12d0U
#define AM13E_GPIO_DOECLR 0x12e0U
#define AM13E_GPIO_DIN 0x1380U
#define AM13E_GPIO_PWREN_KEY 0x26000000U
#define AM13E_GPIO_RSTCTL_KEY 0xb1000000U

typedef struct AM13EGpioPort {
    MemoryRegion mmio;
    uint32_t bank;
    bool powered;
    bool reset_sticky;
    bool unmodeled_reported;
    uint32_t dout;
    uint32_t doe;
} AM13EGpioPort;

struct AM13EMachineState {
    MachineState parent_obj;
    ARMv7MState armv7m;
    MemoryRegion flash;
    MemoryRegion bank3_alias;
    MemoryRegion sysctl;
    bool sysctl_unmodeled_reported;
    uint32_t sysctl_mclkcfg;
    uint32_t sysctl_xtalcr;
    uint32_t sysctl_hsclken;
    uint32_t sysctl_hsclkcfg;
    uint32_t sysctl_hfclkclkcfg;
    uint32_t sysctl_pllcfg0;
    uint32_t sysctl_pllcfg1;
    uint32_t sysctl_pllparam0;
    uint32_t sysctl_pllparam1;
    uint32_t sysctl_clkstatus;
    QEMUTimer *xtal_timer;
    QEMUTimer *sim_pll_timer;
    bool xtal_present;
    bool esc_sim;
    MemoryRegion factory_rom;
    char *factory_pll_file;
    bool factory_pll_loaded;
    uint32_t factory_pll0;
    uint32_t factory_pll1;
    bool factory_unmodeled_reported;
    AM13EGpioPort gpio[AM13E_GPIO_COUNT];
    MemoryRegion fri;
    uint32_t fri_frdcntl;
    bool fri_unmodeled_reported;
    Clock *cpuclk;
    Clock *refclk;
};

/* ESC-SIM: opt-in functional PLL timer; no physical trim/PLL model. */
static void am13e_sim_pll_ready(void *opaque)
{
    AM13EMachineState *s = opaque;
    if (!s->esc_sim || !(s->sysctl_hsclken & AM13E_SYSPLL_ENABLE) ||
        !(s->sysctl_clkstatus & AM13E_HFCLK_GOOD) ||
        (s->sysctl_pllcfg0 & 0x31U) != 0x11U ||
        (s->sysctl_pllcfg1 & 0x7f03U) != 0x1f01U ||
        s->sysctl_pllparam0 != s->factory_pll0 ||
        s->sysctl_pllparam1 != s->factory_pll1) {
        return;
    }
    s->sysctl_clkstatus &= ~AM13E_SIM_SYSPLLOFF;
    s->sysctl_clkstatus |= AM13E_SIM_PLLGOOD;
    if (!(s->sysctl_hsclkcfg & 1U)) {
        s->sysctl_clkstatus |= AM13E_SIM_HSCLKGOOD;
    }
}

static bool am13e_get_esc_sim(Object *obj, Error **errp)
{
    return AM13E_MACHINE(obj)->esc_sim;
}

static void am13e_set_esc_sim(Object *obj, bool on, Error **errp)
{
    AM13E_MACHINE(obj)->esc_sim = on;
}

/*
 * G2g virtual XTAL fixture:
 * - The external crystal is assumed present ONLY with the explicit
 *   -machine am13e23019,xtal-present=on test option.
 * - After XTAL enable with the monitor enabled, the documented XTALTIME
 *   interval elapses on QEMU_CLOCK_VIRTUAL; no host sleep or always-GOOD bit.
 * - This abstracts oscillator success after nominal startup time, NOT
 *   crystal analog startup physics, clock-frequency verification or IRQs.
 * - With the fixture absent, startup remains unmodeled/off (fail-closed).
 */
static void am13e_xtal_ready(void *opaque)
{
    AM13EMachineState *s = opaque;

    if (!(s->xtal_present || s->esc_sim) ||
        (s->sysctl_xtalcr & 1U) ||
        (s->sysctl_hsclken & 0x00010000U) ||
        !(s->sysctl_hfclkclkcfg & 0x10000000U)) {
        return;
    }
    s->sysctl_clkstatus |= AM13E_HFCLK_GOOD;
    s->sysctl_clkstatus &= ~(AM13E_HFCLK_OFF | AM13E_HSCLK_OFF);
}

static void am13e_xtal_off(AM13EMachineState *s)
{
    timer_del(s->xtal_timer);
    s->sysctl_clkstatus &= ~AM13E_HFCLK_GOOD;
    s->sysctl_clkstatus |= AM13E_HFCLK_OFF;
    /* HSCLKSOFF is the conjunction of HFCLKOFF and SYSPLLOFF. */
    if (s->sysctl_clkstatus & (1U << 14)) {
        s->sysctl_clkstatus |= AM13E_HSCLK_OFF;
    }
}

static void am13e_xtal_enable(AM13EMachineState *s)
{
    int64_t ns;

    if (!(s->xtal_present || s->esc_sim) ||
        (s->sysctl_hsclken & 0x00010000U) ||
        !(s->sysctl_hfclkclkcfg & 0x10000000U)) {
        /* No physical XTAL is inferred from a firmware enable request. */
        return;
    }
    ns = (int64_t)(s->sysctl_hfclkclkcfg & 0xffU) *
         AM13E_XTAL_STARTUP_NS_PER_UNIT;
    /* At zero XTALTIME, keep a distinct asynchronous completion event. */
    if (ns == 0) {
        ns = 1;
    }
    s->sysctl_clkstatus &= ~(AM13E_HFCLK_GOOD |
                             AM13E_HFCLK_OFF | AM13E_HSCLK_OFF);
    timer_mod(s->xtal_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + ns);
}

static bool am13e_get_xtal_present(Object *obj, Error **errp)
{
    return AM13E_MACHINE(obj)->xtal_present;
}

static void am13e_set_xtal_present(Object *obj, bool present, Error **errp)
{
    AM13E_MACHINE(obj)->xtal_present = present;
}

/* All other undocumented SYSCTL accesses remain rejected. */
static MemTxResult am13e_sysctl_unmodeled(AM13EMachineState *s,
                                         hwaddr offset,
                                         bool write, unsigned size)
{
    if (!s->sysctl_unmodeled_reported) {
        error_report("G2_UNMODELED_SYSCTL %s 0x%08" PRIx64 " size=%u "
                     "(transaction rejected)",
                     write ? "write" : "read",
                     (uint64_t)(AM13E_SYSCTL_BASE + offset), size);
        s->sysctl_unmodeled_reported = true;
    }
    return MEMTX_ERROR;
}

static MemTxResult am13e_sysctl_read(void *opaque, hwaddr offset,
                                    uint64_t *value, unsigned size,
                                    MemTxAttrs attrs)
{
    AM13EMachineState *s = opaque;

    if (size != 4) {
        return am13e_sysctl_unmodeled(s, offset, false, size);
    }
    switch (offset) {
    case AM13E_SYSCTL_MCLKCFG:
        *value = s->sysctl_mclkcfg;
        return MEMTX_OK;
    case AM13E_SYSCTL_CLKSTATUS:
        *value = s->sysctl_clkstatus;
        return MEMTX_OK;
    case AM13E_SYSCTL_XTALCR:
        *value = s->sysctl_xtalcr;
        return MEMTX_OK;
    case AM13E_SYSCTL_HSCLKEN:
        *value = s->sysctl_hsclken;
        return MEMTX_OK;
    case AM13E_SIM_HSCLKCFG:
        *value = s->sysctl_hsclkcfg;
        return MEMTX_OK;
    case AM13E_SYSCTL_HFCLKCLKCFG:
        *value = s->sysctl_hfclkclkcfg;
        return MEMTX_OK;
    case AM13E_SYSCTL_SYSPLLCFG0:
        *value = s->sysctl_pllcfg0;
        return MEMTX_OK;
    case AM13E_SYSCTL_SYSPLLCFG1:
        *value = s->sysctl_pllcfg1;
        return MEMTX_OK;
    case AM13E_SYSCTL_SYSPLLPARAM0:
        *value = s->sysctl_pllparam0;
        return MEMTX_OK;
    case AM13E_SYSCTL_SYSPLLPARAM1:
        *value = s->sysctl_pllparam1;
        return MEMTX_OK;
    default:
        return am13e_sysctl_unmodeled(s, offset, false, size);
    }
}

static MemTxResult am13e_sysctl_write(void *opaque, hwaddr offset,
                                     uint64_t value, unsigned size,
                                     MemTxAttrs attrs)
{
    AM13EMachineState *s = opaque;
    uint32_t next, div;

    if (size != 4) {
        return am13e_sysctl_unmodeled(s, offset, true, size);
    }
    if (offset == AM13E_SYSCTL_SYSPLLPARAM0 ||
        offset == AM13E_SYSCTL_SYSPLLPARAM1) {
        /* The factory pair is copied verbatim, including R/W-X bits:
         * this is digital register transport, NOT analog calibration.
         * Hardware blocks parameter writes after PLL enable.
         */
        if (s->sysctl_hsclken & AM13E_SYSPLL_ENABLE) {
            return am13e_sysctl_unmodeled(s, offset, true, size);
        }
        if (offset == AM13E_SYSCTL_SYSPLLPARAM0) {
            s->sysctl_pllparam0 = (uint32_t)value;
        } else {
            s->sysctl_pllparam1 = (uint32_t)value;
        }
        return MEMTX_OK;
    }
    if (offset == AM13E_SYSCTL_SYSPLLCFG0 ||
        offset == AM13E_SYSCTL_SYSPLLCFG1) {
        uint32_t *reg = offset == AM13E_SYSCTL_SYSPLLCFG0 ?
                        &s->sysctl_pllcfg0 : &s->sysctl_pllcfg1;
        uint32_t mask = offset == AM13E_SYSCTL_SYSPLLCFG0 ?
                        AM13E_SYSCTL_SYSPLLCFG0_FIELDS :
                        AM13E_SYSCTL_SYSPLLCFG1_FIELDS;
        next = (uint32_t)value;
        /* SYSPLL must be disabled during configuration. A register
         * write is not PLL startup, lock, or successful calibration.
         * Reject unknown reserved bits and invalid QDIV encodings.
         */
        if ((s->sysctl_hsclken & AM13E_SYSPLL_ENABLE) ||
            ((next ^ *reg) & ~mask) ||
            (offset == AM13E_SYSCTL_SYSPLLCFG1 &&
             (((next >> 8) & 0x7fU) == 0U ||
              ((next >> 8) & 0x7fU) > 0x7eU))) {
            return am13e_sysctl_unmodeled(s, offset, true, size);
        }
        *reg = next;
        return MEMTX_OK;
    }
    if (offset == AM13E_SYSCTL_HFCLKCLKCFG) {
        next = (uint32_t)value;
        /* XTALTIME is a programmed startup interval, not proof that
         * oscillator startup has completed. HFCLKFLTCHK only configures
         * the monitor. No CLKSTATUS effects before virtual-time engine.
         */
        if ((next ^ s->sysctl_hfclkclkcfg) &
            ~AM13E_SYSCTL_HFCLKCLKCFG_FIELDS) {
            return am13e_sysctl_unmodeled(s, offset, true, size);
        }
        s->sysctl_hfclkclkcfg = next;
        return MEMTX_OK;
    }
    if (offset == AM13E_SIM_HSCLKCFG) {
        next = (uint32_t)value;
        if ((next ^ s->sysctl_hsclkcfg) & ~1U) {
            return am13e_sysctl_unmodeled(s, offset, true, size);
        }
        s->sysctl_hsclkcfg = next;
        if (s->esc_sim) {
            if ((next & 1U) ? (s->sysctl_clkstatus & AM13E_HFCLK_GOOD) :
                              (s->sysctl_clkstatus & AM13E_SIM_PLLGOOD)) {
                s->sysctl_clkstatus |= AM13E_SIM_HSCLKGOOD;
            } else {
                s->sysctl_clkstatus &= ~AM13E_SIM_HSCLKGOOD;
            }
        }
        return MEMTX_OK;
    }
    if (offset == AM13E_SYSCTL_HSCLKEN) {
        next = (uint32_t)value;
        /* Accept only modeled control bits. These are enable/source
         * requests, not completion events. Never synthesize HFCLKGOOD
         * or SYSPLLGOOD in this stage.
         */
        if ((next ^ s->sysctl_hsclken) &
            ~AM13E_SYSCTL_HSCLKEN_FIELDS) {
            return am13e_sysctl_unmodeled(s, offset, true, size);
        }
        if (!(s->sysctl_hsclken & 0x00010000U) &&
            (next & 0x00010000U)) {
            /* XTAL is no longer selected as the HFCLK source. */
            am13e_xtal_off(s);
        }
        if (s->esc_sim && ((next ^ s->sysctl_hsclken) &
                           AM13E_SYSPLL_ENABLE)) {
            if (next & AM13E_SYSPLL_ENABLE) {
                if ((s->sysctl_clkstatus & AM13E_HFCLK_GOOD) &&
                    (s->sysctl_pllcfg0 & 0x31U) == 0x11U &&
                    (s->sysctl_pllcfg1 & 0x7f03U) == 0x1f01U &&
                    s->sysctl_pllparam0 == s->factory_pll0 &&
                    s->sysctl_pllparam1 == s->factory_pll1) {
                    s->sysctl_clkstatus &= ~AM13E_SIM_SYSPLLOFF;
                    timer_mod(s->sim_pll_timer,
                              qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
                              AM13E_SIM_PLL_NS);
                }
            } else {
                timer_del(s->sim_pll_timer);
                s->sysctl_clkstatus &= ~(AM13E_SIM_PLLGOOD |
                                          AM13E_SIM_HSCLKGOOD |
                                          AM13E_SIM_HSCLKMUX);
                s->sysctl_clkstatus |= AM13E_SIM_SYSPLLOFF;
            }
        }
        s->sysctl_hsclken = next;
        return MEMTX_OK;
    }
    if (offset == AM13E_SYSCTL_XTALCR) {
        next = (uint32_t)value;
        /* Reserved bits 31:2 are not modeled; preserve reset=0.
         * OSCOFF=0 is only a request to run the oscillator.
         * CLKSTATUS remains OFF until a future virtual-time model
         * has proved that the startup interval elapsed.
         */
        if ((next ^ s->sysctl_xtalcr) &
            ~AM13E_SYSCTL_XTALCR_WRITABLE) {
            return am13e_sysctl_unmodeled(s, offset, true, size);
        }
        if (!(s->sysctl_xtalcr & 1U) && (next & 1U)) {
            am13e_xtal_off(s);
        }
        if ((s->sysctl_xtalcr & 1U) && !(next & 1U)) {
            /* Request a new oscillator start; allow rearming only
             * after the previous OFF state was reached.
             */
            am13e_xtal_enable(s);
        }
        s->sysctl_xtalcr = next;
        return MEMTX_OK;
    }
    if (offset != AM13E_SYSCTL_MCLKCFG) {
        return am13e_sysctl_unmodeled(s, offset, true, size);
    }
    next = (uint32_t)value;
    div = (next & AM13E_SYSCTL_MCLKDIVCFG_MASK) >> 24;
    /*
     * G2c implements only legal MCLKDIVCFG encodings, not a writable
     * generic SYSCTL register. Reject any attempt to change unmodeled
     * fields such as USEHSCLK or reserved bits. The firmware writes
     * the full 32-bit word after a read-modify-write.
     */
    if (((next ^ s->sysctl_mclkcfg) &
         ~(AM13E_SYSCTL_MCLKDIVCFG_MASK |
           (s->esc_sim ? 0x00010000U : 0U))) != 0 ||
        (s->esc_sim && (next & 0x00010000U) &&
         !(s->sysctl_clkstatus & AM13E_SIM_HSCLKGOOD)) ||
        (div != 0 && div != 1 && div != 3 && div != 5 && div != 7)) {
        return am13e_sysctl_unmodeled(s, offset, true, size);
    }
    if (s->esc_sim) {
        if (next & 0x00010000U) {
            s->sysctl_clkstatus |= AM13E_SIM_HSCLKMUX;
        } else {
            s->sysctl_clkstatus &= ~AM13E_SIM_HSCLKMUX;
        }
    }
    s->sysctl_mclkcfg = next;
    return MEMTX_OK;
}

static const MemoryRegionOps am13e_sysctl_ops = {
    .read_with_attrs = am13e_sysctl_read,
    .write_with_attrs = am13e_sysctl_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {
        .min_access_size = 4,
        .max_access_size = 4,
    },
};

/*
 * G2i: the application copies two per-chip PLL startup words from
 * FACTORY region 0x60111028/2c. There is no universal calibration
 * value embedded in the SDK or in the original firmware ELF.
 *
 * An explicitly supplied, exactly 8-byte little-endian binary pair
 * enables read-only MMIO transport. Without it the memory read MUST
 * BusFault, rather than manufacture plausible silicon calibration.
 * The provenance of any supplied bytes remains the caller's duty;
 * G2i does not imply physical PLL or board qualification.
 */
static MemTxResult am13e_factory_unavailable(AM13EMachineState *s,
                                             hwaddr offset, bool write,
                                             unsigned size)
{
    if (!s->factory_unmodeled_reported) {
        error_report("G2_FACTORY_UNAVAILABLE %s 0x%08" PRIx64 " size=%u "
                     "fixture=%s (transaction rejected)",
                     write ? "write" : "read",
                     (uint64_t)(AM13E_FACTORY_BASE + offset), size,
                     s->factory_pll_loaded ? "provided" : "absent");
        s->factory_unmodeled_reported = true;
    }
    return MEMTX_ERROR;
}

static MemTxResult am13e_factory_read(void *opaque, hwaddr offset,
                                     uint64_t *value, unsigned size,
                                     MemTxAttrs attrs)
{
    AM13EMachineState *s = opaque;

    if (size != 4 || !s->factory_pll_loaded) {
        return am13e_factory_unavailable(s, offset, false, size);
    }
    switch (offset) {
    case AM13E_FACTORY_PLL0_OFFSET:
        *value = s->factory_pll0;
        return MEMTX_OK;
    case AM13E_FACTORY_PLL1_OFFSET:
        *value = s->factory_pll1;
        return MEMTX_OK;
    default:
        return am13e_factory_unavailable(s, offset, false, size);
    }
}

static MemTxResult am13e_factory_write(void *opaque, hwaddr offset,
                                      uint64_t value, unsigned size,
                                      MemTxAttrs attrs)
{
    AM13EMachineState *s = opaque;

    return am13e_factory_unavailable(s, offset, true, size);
}

static const MemoryRegionOps am13e_factory_ops = {
    .read_with_attrs = am13e_factory_read,
    .write_with_attrs = am13e_factory_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {
        .min_access_size = 4,
        .max_access_size = 4,
    },
};

static void am13e_load_factory_pll_fixture(AM13EMachineState *s)
{
    GError *error = NULL;
    gchar *data = NULL;
    gsize size = 0;
    uint32_t word0, word1;

    if (!s->factory_pll_file) {
        if (s->esc_sim) {
            /* Synthetic transport only: reset snapshots are NOT TI trim. */
            s->factory_pll0 = AM13E_SYSCTL_SYSPLLPARAM0_INITIAL;
            s->factory_pll1 = AM13E_SYSCTL_SYSPLLPARAM1_INITIAL;
            s->factory_pll_loaded = true;
            warn_report("ESC_SIM uses synthetic PLL parameters; "
                        "no silicon calibration or timing accuracy");
        }
        return;
    }
    if (!g_file_get_contents(s->factory_pll_file, &data, &size, &error)) {
        error_report("G2_FACTORY_FILE_ERROR '%s': %s",
                     s->factory_pll_file, error->message);
        g_clear_error(&error);
        exit(EXIT_FAILURE);
    }
    if (size != 8) {
        error_report("G2_FACTORY_FILE_INVALID '%s': expected exactly "
                     "8 bytes, got %" G_GSIZE_FORMAT,
                     s->factory_pll_file, size);
        g_free(data);
        exit(EXIT_FAILURE);
    }
    memcpy(&word0, data, sizeof(word0));
    memcpy(&word1, data + 4, sizeof(word1));
    s->factory_pll0 = GUINT32_FROM_LE(word0);
    s->factory_pll1 = GUINT32_FROM_LE(word1);
    s->factory_pll_loaded = true;
    g_free(data);
    /* No attestation of device identity or factory provenance is possible. */
}

static char *am13e_get_factory_pll_file(Object *obj, Error **errp)
{
    AM13EMachineState *s = AM13E_MACHINE(obj);

    return g_strdup(s->factory_pll_file ? s->factory_pll_file : "");
}

static void am13e_set_factory_pll_file(Object *obj, const char *value,
                                      Error **errp)
{
    AM13EMachineState *s = AM13E_MACHINE(obj);

    g_free(s->factory_pll_file);
    s->factory_pll_file = (value && value[0]) ? g_strdup(value) : NULL;
}

/*
 * G2b: FRI register read/write semantics only. Real Flash read latency,
 * MCLK timekeeping, and the TRM nine-cycle pipeline requirement are
 * deliberately not modeled; the real SDK RAMFUNC performs FRI writes.
 */
static MemTxResult am13e_fri_unmodeled(AM13EMachineState *s,
                                      hwaddr offset, bool write,
                                      unsigned size)
{
    if (!s->fri_unmodeled_reported) {
        error_report("G2_UNMODELED_FRI %s 0x%08" PRIx64 " size=%u "
                     "(transaction rejected)",
                     write ? "write" : "read",
                     (uint64_t)(AM13E_FRI_BASE + offset), size);
        s->fri_unmodeled_reported = true;
    }
    return MEMTX_ERROR;
}

static MemTxResult am13e_fri_read(void *opaque, hwaddr offset,
                                 uint64_t *value, unsigned size,
                                 MemTxAttrs attrs)
{
    AM13EMachineState *s = opaque;

    if (size != 4 || offset != AM13E_FRI_FRDCNTL) {
        return am13e_fri_unmodeled(s, offset, false, size);
    }
    *value = s->fri_frdcntl;
    return MEMTX_OK;
}

static MemTxResult am13e_fri_write(void *opaque, hwaddr offset,
                                  uint64_t value, unsigned size,
                                  MemTxAttrs attrs)
{
    AM13EMachineState *s = opaque;

    if (size != 4 || offset != AM13E_FRI_FRDCNTL) {
        return am13e_fri_unmodeled(s, offset, true, size);
    }
    /* Only known, documented firmware-operated bits change state.
     * All other register bits retain their reset state.
     */
    s->fri_frdcntl = (s->fri_frdcntl & ~AM13E_FRI_FRDCNTL_FIELDS) |
                     ((uint32_t)value & AM13E_FRI_FRDCNTL_FIELDS);
    return MEMTX_OK;
}

static const MemoryRegionOps am13e_fri_ops = {
    .read_with_attrs = am13e_fri_read,
    .write_with_attrs = am13e_fri_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {
        .min_access_size = 4,
        .max_access_size = 4,
    },
};


/*
 * G3a: GPIO Power/Reset and minimal digital register aliases.
 * The first MMIO fault after ESC-SIM SYSPLL startup was at
 * GPIO0.GPRCM.PWREN (0x400F0800) with R2=0x26000001.
 * No generic "always ready" or full GPIO register map is assumed.
 *
 * DIN reports only internally driven digital GPIO outputs, with
 * no external stimulus or PINCM/peripheral routing connected yet.
 * Future DShot pin injection must use the TIMG4 capture path.
 */
static void am13e_gpio_reset_port(AM13EGpioPort *g)
{
    g->powered = false;
    g->reset_sticky = false;
    g->unmodeled_reported = false;
    g->dout = 0;
    g->doe = 0;
}

static MemTxResult am13e_gpio_unmodeled(AM13EGpioPort *g,
                                       hwaddr offset, bool write,
                                       unsigned size)
{
    if (!g->unmodeled_reported) {
        error_report("G3_UNMODELED_GPIO%u %s 0x%08" PRIx64
                     " size=%u powered=%u (transaction rejected)",
                     g->bank, write ? "write" : "read",
                     (uint64_t)(AM13E_GPIO_BASE +
                       g->bank * AM13E_GPIO_STRIDE + offset),
                     size, g->powered ? 1U : 0U);
        g->unmodeled_reported = true;
    }
    return MEMTX_ERROR;
}

static MemTxResult am13e_gpio_read(void *opaque, hwaddr offset,
                                  uint64_t *value, unsigned size,
                                  MemTxAttrs attrs)
{
    AM13EGpioPort *g = opaque;

    if (size != 4) {
        return am13e_gpio_unmodeled(g, offset, false, size);
    }
    switch (offset) {
    case AM13E_GPIO_PWREN:
        /* KEY is write-only; the ENABLE field is readable. */
        *value = g->powered ? 1U : 0U;
        return MEMTX_OK;
    case AM13E_GPIO_STAT:
        *value = g->reset_sticky ? (1U << 16) : 0U;
        return MEMTX_OK;
    default:
        break;
    }
    if (!g->powered) {
        return am13e_gpio_unmodeled(g, offset, false, size);
    }
    switch (offset) {
    case AM13E_GPIO_DOE:
        *value = g->doe;
        return MEMTX_OK;
    case AM13E_GPIO_DIN:
        /* Digital-only internal drive readback. External levels are
         * intentionally absent until explicit pin/plant injection.
         */
        *value = g->dout & g->doe;
        return MEMTX_OK;
    default:
        return am13e_gpio_unmodeled(g, offset, false, size);
    }
}

static MemTxResult am13e_gpio_write(void *opaque, hwaddr offset,
                                   uint64_t value, unsigned size,
                                   MemTxAttrs attrs)
{
    AM13EGpioPort *g = opaque;
    uint32_t data = (uint32_t)value;

    if (size != 4) {
        return am13e_gpio_unmodeled(g, offset, true, size);
    }
    switch (offset) {
    case AM13E_GPIO_PWREN:
        if ((data & 0xff000000U) != AM13E_GPIO_PWREN_KEY ||
            (data & 0x00fffffeU)) {
            return am13e_gpio_unmodeled(g, offset, true, size);
        }
        g->powered = (data & 1U) != 0U;
        return MEMTX_OK;
    case AM13E_GPIO_RSTCTL:
        if ((data & 0xff000000U) != AM13E_GPIO_RSTCTL_KEY ||
            (data & 0x00fffffcU)) {
            return am13e_gpio_unmodeled(g, offset, true, size);
        }
        if (data & 1U) {
            g->dout = 0;
            g->doe = 0;
            g->reset_sticky = true;
        } else if (data & 2U) {
            g->reset_sticky = false;
        }
        return MEMTX_OK;
    default:
        break;
    }
    if (!g->powered) {
        return am13e_gpio_unmodeled(g, offset, true, size);
    }
    switch (offset) {
    case AM13E_GPIO_DOUT:
        g->dout = data;
        return MEMTX_OK;
    case AM13E_GPIO_DOUTSET:
        g->dout |= data;
        return MEMTX_OK;
    case AM13E_GPIO_DOUTCLR:
        g->dout &= ~data;
        return MEMTX_OK;
    case AM13E_GPIO_DOUTTGL:
        g->dout ^= data;
        return MEMTX_OK;
    case AM13E_GPIO_DOE:
        g->doe = data;
        return MEMTX_OK;
    case AM13E_GPIO_DOESET:
        g->doe |= data;
        return MEMTX_OK;
    case AM13E_GPIO_DOECLR:
        g->doe &= ~data;
        return MEMTX_OK;
    default:
        return am13e_gpio_unmodeled(g, offset, true, size);
    }
}

static const MemoryRegionOps am13e_gpio_ops = {
    .read_with_attrs = am13e_gpio_read,
    .write_with_attrs = am13e_gpio_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {
        .min_access_size = 4,
        .max_access_size = 4,
    },
};

/*
 * Model the state at the END of the real ESCape32 Bootloader handoff:
 * __disable_irq(); quiesce(); VTOR=APP; MSP=vector[0]; BX vector[1].
 * This is NOT silicon reset and it does NOT emulate Boot validation.
 * Reset ordering: this callback is registered after armv7m_load_kernel's
 * CPU reset callback. The application itself owns IRQ release.
 */
static void am13e_handoff_reset(void *opaque)
{
    AM13EMachineState *s = opaque;
    CPUARMState *env = &s->armv7m.cpu->env;

    g_assert(!arm_feature(env, ARM_FEATURE_M_SECURITY));
    g_assert(env->v7m.vecbase[M_REG_NS] == AM13E_APP_BASE);
    env->v7m.primask[M_REG_NS] = 1;
    s->sysctl_mclkcfg = AM13E_SYSCTL_MCLKCFG_INITIAL;
    s->sysctl_xtalcr = AM13E_SYSCTL_XTALCR_INITIAL;
    s->sysctl_hsclken = AM13E_SYSCTL_HSCLKEN_INITIAL;
    s->sysctl_hsclkcfg = 0;
    s->sysctl_hfclkclkcfg = AM13E_SYSCTL_HFCLKCLKCFG_INITIAL;
    s->sysctl_pllcfg0 = AM13E_SYSCTL_SYSPLLCFG0_INITIAL;
    s->sysctl_pllcfg1 = AM13E_SYSCTL_SYSPLLCFG1_INITIAL;
    s->sysctl_pllparam0 = AM13E_SYSCTL_SYSPLLPARAM0_INITIAL;
    s->sysctl_pllparam1 = AM13E_SYSCTL_SYSPLLPARAM1_INITIAL;
    s->sysctl_clkstatus = AM13E_SYSCTL_CLKSTATUS_INITIAL;
    timer_del(s->xtal_timer);
    timer_del(s->sim_pll_timer);
    s->sysctl_unmodeled_reported = false;
    s->fri_frdcntl = AM13E_FRI_FRDCNTL_RESET;
    s->fri_unmodeled_reported = false;
    s->factory_unmodeled_reported = false;
    for (unsigned i = 0; i < AM13E_GPIO_COUNT; ++i) {
        am13e_gpio_reset_port(&s->gpio[i]);
    }
}

static void am13e_init(MachineState *machine)
{
    AM13EMachineState *s = AM13E_MACHINE(machine);
    MachineClass *mc = MACHINE_GET_CLASS(machine);
    MemoryRegion *sysmem = get_system_memory();
    DeviceState *core;

    if (machine->ram_size != AM13E_SRAM_SIZE ||
        strcmp(machine->cpu_type, mc->default_cpu_type)) {
        error_report("am13e23019 requires 128KiB SRAM and cortex-m33-am13e");
        exit(EXIT_FAILURE);
    }
    memory_region_init_rom(&s->flash, NULL, "am13e-main-flash",
                           AM13E_FLASH_SIZE, &error_fatal);
    memory_region_add_subregion(sysmem, 0x00000000, &s->flash);

    /* All four SRAM banks use the same contiguous 128KiB backing. */
    memory_region_add_subregion(sysmem, 0x20000000, machine->ram);

    /* Bank3's 32KiB code alias MUST share physical bytes with SRAM. */
    memory_region_init_alias(&s->bank3_alias, NULL,
                             "am13e-bank3-code-alias", machine->ram,
                             96 * KiB, 32 * KiB);
    memory_region_add_subregion(sysmem, 0x00c18000, &s->bank3_alias);

    /* SYSCTL G2a-G2f: readback and oscillator/PLL configuration only. */
    s->sysctl_mclkcfg = AM13E_SYSCTL_MCLKCFG_INITIAL;
    s->sysctl_xtalcr = AM13E_SYSCTL_XTALCR_INITIAL;
    s->sysctl_hsclken = AM13E_SYSCTL_HSCLKEN_INITIAL;
    s->sysctl_hsclkcfg = 0;
    s->sysctl_hfclkclkcfg = AM13E_SYSCTL_HFCLKCLKCFG_INITIAL;
    s->sysctl_pllcfg0 = AM13E_SYSCTL_SYSPLLCFG0_INITIAL;
    s->sysctl_pllcfg1 = AM13E_SYSCTL_SYSPLLCFG1_INITIAL;
    s->sysctl_pllparam0 = AM13E_SYSCTL_SYSPLLPARAM0_INITIAL;
    s->sysctl_pllparam1 = AM13E_SYSCTL_SYSPLLPARAM1_INITIAL;
    s->sysctl_clkstatus = AM13E_SYSCTL_CLKSTATUS_INITIAL;
    s->xtal_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, am13e_xtal_ready, s);
    s->sim_pll_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL,
                                    am13e_sim_pll_ready, s);
    memory_region_init_io(&s->sysctl, NULL, &am13e_sysctl_ops, s,
                          "am13e-sysctl-g2a", AM13E_SYSCTL_SIZE);
    memory_region_add_subregion(sysmem, AM13E_SYSCTL_BASE, &s->sysctl);

    /* FACTORY G2i: only caller-provided per-chip PLL startup words. */
    am13e_load_factory_pll_fixture(s);
    memory_region_init_io(&s->factory_rom, NULL, &am13e_factory_ops, s,
                          "am13e-factory-pll-g2i", AM13E_FACTORY_SIZE);
    memory_region_add_subregion(sysmem, AM13E_FACTORY_BASE, &s->factory_rom);

    /* FRI G2b: documented FRDCNTL fields only. */
    s->fri_frdcntl = AM13E_FRI_FRDCNTL_RESET;
    memory_region_init_io(&s->fri, NULL, &am13e_fri_ops, s,
                          "am13e-fri-g2b", AM13E_FRI_SIZE);
    memory_region_add_subregion(sysmem, AM13E_FRI_BASE, &s->fri);

    /* GPIO0..3: power/reset plus basic digital output aliases. */
    static const char *const gpio_names[AM13E_GPIO_COUNT] = {
        "am13e-gpio0", "am13e-gpio1", "am13e-gpio2", "am13e-gpio3"
    };
    for (unsigned i = 0; i < AM13E_GPIO_COUNT; ++i) {
        AM13EGpioPort *g = &s->gpio[i];

        g->bank = i;
        am13e_gpio_reset_port(g);
        memory_region_init_io(&g->mmio, NULL, &am13e_gpio_ops, g,
                              gpio_names[i], AM13E_GPIO_SIZE);
        memory_region_add_subregion(sysmem,
                                    AM13E_GPIO_BASE + i * AM13E_GPIO_STRIDE,
                                    &g->mmio);
    }

    /* Placeholder QEMU clocks, not an AM13E SYSCTL/PLL model. */
    s->cpuclk = clock_new(OBJECT(machine), "CPUCLK");
    clock_set_hz(s->cpuclk, 200000000);
    s->refclk = clock_new(OBJECT(machine), "REFCLK");
    clock_set_hz(s->refclk, 1000000);

    object_initialize_child(OBJECT(machine), "armv7m", &s->armv7m, TYPE_ARMV7M);
    core = DEVICE(&s->armv7m);
    qdev_prop_set_string(core, "cpu-type", machine->cpu_type);
    qdev_prop_set_uint32(core, "num-irq", 64);
    qdev_prop_set_uint32(core, "init-nsvtor", AM13E_APP_BASE);
    qdev_connect_clock_in(core, "cpuclk", s->cpuclk);
    qdev_connect_clock_in(core, "refclk", s->refclk);
    object_property_set_link(OBJECT(&s->armv7m), "memory",
                             OBJECT(sysmem), &error_abort);
    sysbus_realize(SYS_BUS_DEVICE(core), &error_fatal);
    armv7m_load_kernel(ARM_CPU(first_cpu), machine->kernel_filename,
                       AM13E_FLASH_SIZE);
    qemu_register_reset(am13e_handoff_reset, s);
}

static void am13e_class_init(ObjectClass *oc, void *data)
{
    MachineClass *mc = MACHINE_CLASS(oc);
    mc->desc = "AM13E23019 ESC-SIM clock + GPIO power/IO G3a";
    mc->init = am13e_init;
    mc->default_cpu_type = ARM_CPU_TYPE_NAME("cortex-m33-am13e");
    mc->default_ram_size = AM13E_SRAM_SIZE;
    mc->default_ram_id = "am13e.sram";
    mc->max_cpus = 1;
    object_class_property_add_bool(oc, "xtal-present",
                                   am13e_get_xtal_present,
                                   am13e_set_xtal_present);
    object_class_property_set_description(oc, "xtal-present",
        "Provide a virtual crystal fixture; default off, only XTAL clock");
    object_class_property_add_str(oc, "factory-pll-file",
                                  am13e_get_factory_pll_file,
                                  am13e_set_factory_pll_file);
    object_class_property_set_description(oc, "factory-pll-file",
        "Optional 8-byte little-endian factory PLL startup word pair. "
        "No implicit or default silicon calibration is supplied.");
    object_class_property_add_bool(oc, "esc-sim", am13e_get_esc_sim,
                                   am13e_set_esc_sim);
    object_class_property_set_description(oc, "esc-sim",
        "Functional-only ESC simulation (synthetic PLL trim/clock).");
}
static void am13e_finalize(Object *obj)
{
    AM13EMachineState *s = AM13E_MACHINE(obj);

    if (s->xtal_timer) {
        timer_free(s->xtal_timer);
        s->xtal_timer = NULL;
    }
    if (s->sim_pll_timer) {
        timer_free(s->sim_pll_timer);
        s->sim_pll_timer = NULL;
    }
    g_free(s->factory_pll_file);
    s->factory_pll_file = NULL;
}

static const TypeInfo am13e_info = {
    .name = TYPE_AM13E_MACHINE,
    .parent = TYPE_MACHINE,
    .instance_size = sizeof(AM13EMachineState),
    .instance_finalize = am13e_finalize,
    .class_init = am13e_class_init,
};
static void am13e_register(void)
{
    type_register_static(&am13e_info);
}
type_init(am13e_register)
