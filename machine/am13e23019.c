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

struct AM13EMachineState {
    MachineState parent_obj;
    ARMv7MState armv7m;
    MemoryRegion flash;
    MemoryRegion bank3_alias;
    MemoryRegion sysctl;
    bool sysctl_unmodeled_reported;
    uint32_t sysctl_mclkcfg;
    uint32_t sysctl_xtalcr;
    MemoryRegion fri;
    uint32_t fri_frdcntl;
    bool fri_unmodeled_reported;
    Clock *cpuclk;
    Clock *refclk;
};

/*
 * G2a: the only supported SYSCTL accesses are two explicitly grounded,
 * read-only reset snapshots. There is no ready-bit synthesis or
 * permission to access unknown registers. Later G2 iterations must
 * implement real SYSCTL write/power/clock transitions and virtual time.
 */
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
        *value = AM13E_SYSCTL_CLKSTATUS_INITIAL;
        return MEMTX_OK;
    case AM13E_SYSCTL_XTALCR:
        *value = s->sysctl_xtalcr;
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
         ~AM13E_SYSCTL_MCLKDIVCFG_MASK) != 0 ||
        (div != 0 && div != 1 && div != 3 && div != 5 && div != 7)) {
        return am13e_sysctl_unmodeled(s, offset, true, size);
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
    s->sysctl_unmodeled_reported = false;
    s->fri_frdcntl = AM13E_FRI_FRDCNTL_RESET;
    s->fri_unmodeled_reported = false;
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

    /* SYSCTL G2a/G2c/G2d: snapshots, MCLK divider, XTAL control. */
    s->sysctl_mclkcfg = AM13E_SYSCTL_MCLKCFG_INITIAL;
    s->sysctl_xtalcr = AM13E_SYSCTL_XTALCR_INITIAL;
    memory_region_init_io(&s->sysctl, NULL, &am13e_sysctl_ops, s,
                          "am13e-sysctl-g2a", AM13E_SYSCTL_SIZE);
    memory_region_add_subregion(sysmem, AM13E_SYSCTL_BASE, &s->sysctl);

    /* FRI G2b: documented FRDCNTL fields only. */
    s->fri_frdcntl = AM13E_FRI_FRDCNTL_RESET;
    memory_region_init_io(&s->fri, NULL, &am13e_fri_ops, s,
                          "am13e-fri-g2b", AM13E_FRI_SIZE);
    memory_region_add_subregion(sysmem, AM13E_FRI_BASE, &s->fri);

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
    mc->desc = "AM13E23019 ESCape32 app-handoff / G2a-G2d clock MMIO";
    mc->init = am13e_init;
    mc->default_cpu_type = ARM_CPU_TYPE_NAME("cortex-m33-am13e");
    mc->default_ram_size = AM13E_SRAM_SIZE;
    mc->default_ram_id = "am13e.sram";
    mc->max_cpus = 1;
}
static const TypeInfo am13e_info = {
    .name = TYPE_AM13E_MACHINE,
    .parent = TYPE_MACHINE,
    .instance_size = sizeof(AM13EMachineState),
    .class_init = am13e_class_init,
};
static void am13e_register(void)
{
    type_register_static(&am13e_info);
}
type_init(am13e_register)
