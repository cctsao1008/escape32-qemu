# G13B — Native ESCape32 drive-authorization and real PA26 DShot ingress

## Contract and boundary

**The pinned original Rel17.3 Reference ELF has no reviewed electrical
board profile.** In `mcu/AM13E/hal/motor_output_configuration.h`,
`AM13E_MOTOR_OUTPUT_CONFIGURED` is defined as 0 without a complete
explicit board contract. `motor_power_stage.c` consequently retains
PB13 as a GPIO input, and the PWM pad routes are disconnected.
`motor_fault_route.c` requires independent nFAULT and three-phase
overcurrent comparator-to-Trip pathways before physical output
can be enabled. These conditions are deliberate, not simulator defects.

The test must **never** substitute guest writes of `throt`, DMA
buffer, PWM AQ, GPIO PB13 enable, IRQ pending bits or ECAP capture
flags for evidence of native firmware control. G13A already proves
the QTest-programmed virtual power stage/plant feedback mechanism;
G13B has distinct firmware ownership and safety acceptance.

## G13B0 — original-ELF no-command negative case (PASS)

[CI run 39516301125](https://github.com/cctsao1008/escape32-qemu/actions/runs/39516301125)
passed with original application ELF, `icount shift=2`, guest-executed
IRQ release, real SysTick and two actual native WFI breakpoint visits.
Neither native SRAM variables nor silicon registers are written by
the test; it only reads the GDB architectural/MCU snapshots.

```text
G13B0_NATIVE_PRE_CPSIE_GATE_AND_PADS_ISOLATED=PASS
G13B0_WFI_0_NO_NATIVE_DRIVE=PASS tick=1 throt=0 PB13_DOE=0 PB13_PINCM=0x00040081 TBCLKSYNC=0 PWM_OBS=0x4
G13B0_WFI_1_NO_NATIVE_DRIVE=PASS tick=3 throt=0 PB13_DOE=0 PB13_PINCM=0x00040081 TBCLKSYNC=0 PWM_OBS=0x4
PASS_G13B0_ORIGINAL_ELF_NO_COMMAND_NO_DRIVE_TWO_WFI NOT_NATIVE_CLOSED_LOOP
```

Absence of an input frame is a negative case only. It does not
demonstrate positive DShot acceptance, arming or motor drive.

## G13B1 — a real external signal, not a mocked firmware callback

Existing G7B proved that an external physical PA26 input level
can be captured by configured native TIMG4_0 CCP0 and transported
via native DMA0 CH2 trigger 34 to a guest SRAM buffer.
Ordinary QEMU memory writes cannot precisely time 32 edges
while the guest CPU is running; a **test-only external waveform**
controller at `0x5FFE4000` solves that without changing firmware.

Supported simulator-only registers (32-bit aligned):

| Offset | Access | Semantics |
|---|---|---|
| `+0x00` | W | Next edge delay in QEMU virtual ns (10 to 100,000,000) |
| `+0x04` | W | Next external PA26 logical line level (0 or 1) |
| `+0x08` | R | Number of staged edges |
| `+0x0C` | R | Number of delivered physical transitions |
| `+0x10` | R | Waveform execution busy |
| `+0x14` | R | Current external PA26 level |
| `+0x18` | W | Commit one staged edge (write 1) |
| `+0x1C` | W | Start from current QEMU virtual time (write 1) |
| `+0x20` | W | Clear idle event queue (write 1) |

The timer callback calls **only** G7B's PA26 external-level input
handler. That handler independently checks GPIO power, PA26 PINCM
input function, TIMG4 capture mode, channel event mask, DMA trigger
34 and channel arm. The new input source does not parse DShot,
force TIMG4/DMA events, patch firmware SRAM or invoke an ISR.
Waveforms are explicit physical rising/falling transitions only.

`tests/g13b_pa26_waveform.py` uses QTest to verify external timed
DShot600 edges traverse native TIMG4 CC0 and DMA CH2 without direct
buffer writes. `tests/g13b_native_dshot.py` uses GDB to halt the
**original** firmware only at its existing first WFI, send a
32-edge DShot600 physical waveform, resume native CPU and wait
for entry to the **real original**
`am13e_app_io_dshot_packet()` function with the expected frame.
The test must additionally confirm real capture/DMA evidence and
that PB13 remains physically disconnected.

The independently configured QTest ingress has already passed
[CI run 39516680718](https://github.com/cctsao1008/escape32-qemu/actions/runs/39516680718):
the exact physical-edge queue delivered 32 transitions into
TIMG4 Capture and 32 DMA0 CH2 SRAM beats, reproducing DShot600
frame `0x7D0A`. This does **not** prove the guest decoder was run.

The first native attempt,
[CI run 39516817766](https://github.com/cctsao1008/escape32-qemu/actions/runs/39516817766),
failed **before** DShot decode: writing the test-only external
signal MMIO via GDB RSP `M` returned OK but did not enqueue a
physical edge. QEMU 6.2.0 `cpu_memory_rw_debug()` uses
`address_space_write_rom()` for debug writes, which intentionally
does not dispatch an MMIO MemoryRegionOps write. The test harness
now uses a **separate QTest socket** for genuinely dispatched
`writel` commands while TCG/GDB runs the unchanged native guest.
GDB retains read-only observation/breakpoint responsibilities.

**Original ELF callback entry is now verified** by
[CI run 39517608065](https://github.com/cctsao1008/escape32-qemu/actions/runs/39517608065).
Unlike the first GDB-write attempt, QTest on a separate socket really
committed 32 external physical PA26 level changes, and QEMU TCG
executed the original guest ISR/decoder. The genuine native
`am13e_app_io_dshot_packet` function was reached with:

```text
G13B1_REAL_INPUT_FRAME=0x7d0a PA26_EDGES_SCHEDULED=32
G13B1_NATIVE_RECEIVE_CALLBACK capture=32 delivered=32 dma_beats=32 dma_remaining=0 guest_frame=0x7d0a inverted=0 ipsr=56 gate_disconnected=true throttle_pre_callback=0
PASS_G13B1_ORIGINAL_ELF_DSHOT_RX_FROM_PA26_WIRE
```

The next stricter acceptance separately executes the **real callback
body and return** and requires CRC return-value success and a change to
the original firmware-owned `throt` global with gate still isolated.
Merely entering that function is **not proof of CRC acceptance**.

Even a real
callback proves only command **ingress**, not successful arming,
positive PWM gate authorization, valid BEMF zero-cross consumption,
motor spin-up or closed-loop speed/commutation control.

## G13B2 positive closed-loop prerequisites — OPEN

A separate QEMU-only virtual electrical-board profile must specify
its own explicit gate polarity, six pads/inversions, RED/FED/minimum
dead time, nFAULT status/Trip route, independent three-phase OC
routing/thresholds and reset-inactive behavior. Such fixture values
must **not** be labeled E62/AM13E production BOM values.

After a board test fixture passes all protection checks, the
original firmware must itself consume legitimate input, satisfy
its actual neutral arming window, command MCPWM4 output/gate
through native register writes, and respond to repeated genuine
CMPSS0→ECAP1 capture edges with causally observable commutation.
A QTest-programmed AQ image (G13A) and a passive DShot callback
(G13B1) are insufficient to claim G13B2 closure.
