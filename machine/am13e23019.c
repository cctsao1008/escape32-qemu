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

struct AM13EMachineState {
    MachineState parent_obj;
    ARMv7MState armv7m;
    MemoryRegion flash;
    MemoryRegion bank3_alias;
    Clock *cpuclk;
    Clock *refclk;
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
    mc->desc = "AM13E23019 ESCape32 app-handoff prototype (G1)";
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
