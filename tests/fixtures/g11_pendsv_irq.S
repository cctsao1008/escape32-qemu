/* G11 independent architectural control: PENDSV exception entry/return.
 * This is a separate test-only firmware, NOT a replacement for ESCape32.
 * The board's handoff reset sets PRIMASK=1, and our own code unmasks it.
 */
.syntax unified
.cpu cortex-m33
.thumb

.section .isr_vector, "a", %progbits
.align 2
.word 0x20018000
.word Reset_Handler
.word Default_Handler
.word HardFault_Handler
.word Default_Handler
.word Default_Handler
.word Default_Handler
.word 0
.word 0
.word 0
.word 0
.word Default_Handler
.word Default_Handler
.word 0
.word PendSV_Handler
.word Default_Handler

.section .text, "ax", %progbits
.align 2
.thumb_func
.global Reset_Handler
.type Reset_Handler, %function
Reset_Handler:
    ldr r0, =0x20000000
    movs r1, #0
    str r1, [r0]
    str r1, [r0, #4]
    /* PendSV is now pending, but must not run while PRIMASK=1. */
    ldr r0, =0xe000ed04
    ldr r1, =0x10000000
    str r1, [r0]
    cpsie i
    /* Successful IRQ unstack returns to this instruction sequence. */
    ldr r0, =0x20000000
    ldr r1, [r0]
    cmp r1, #1
    bne failed
    movs r1, #0x5a
    str r1, [r0, #4]
stop:
    b stop
failed:
    movs r1, #0xee
    str r1, [r0, #4]
    b stop
.size Reset_Handler, . - Reset_Handler

.align 2
.thumb_func
.global PendSV_Handler
.type PendSV_Handler, %function
PendSV_Handler:
    ldr r0, =0x20000000
    ldr r1, [r0]
    adds r1, #1
    str r1, [r0]
    bx lr
.size PendSV_Handler, . - PendSV_Handler

.align 2
.thumb_func
.global HardFault_Handler
.type HardFault_Handler, %function
HardFault_Handler:
    ldr r0, =0x20000004
    movs r1, #0xff
    str r1, [r0]
halt_fault:
    b halt_fault
.size HardFault_Handler, . - HardFault_Handler

.align 2
.thumb_func
.global Default_Handler
.type Default_Handler, %function
Default_Handler:
    b .
.size Default_Handler, . - Default_Handler
