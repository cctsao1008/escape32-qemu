/* G11 micro-firmware only, original ESCape32 linker remains unchanged. */
ENTRY(Reset_Handler)
MEMORY {
    APP (rx) : ORIGIN = 0x00006000, LENGTH = 448K
    SRAM (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
}
SECTIONS {
    .isr_vector : { KEEP(*(.isr_vector)) } > APP
    .text : { *(.text*) *(.rodata*) } > APP
    .ARM.exidx : { *(.ARM.exidx*) } > APP
    .data : { *(.data*) } > SRAM AT > APP
    .bss (NOLOAD) : { *(.bss*) *(COMMON) } > SRAM
}
