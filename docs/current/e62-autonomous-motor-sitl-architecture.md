# E62 — Autonomous Motor-Coupled SITL Architecture Correction

**2026-10-27 | Direct-main implementation contract**

## Decision

The G17–G20 host-coupled WFI-stop → historical PWM replay → BEMF injection pipeline is **not** autonomous ESC–motor closed-loop SITL. The separate G13B5 autonomous DShot fixture uses synthetic timed BEMF rather than rotor-generated BEMF. These are both useful limited-scope tests, not substitutes for the requested behavior.

```text
Autonomous external DShot -> PA26/TIMG4/DMA -> unchanged ESCape32 Rel17 Guest
                                                |
                                                v
                 MCPWM4 actual AQ/DB/PB13/Trip switching -> Motor Plant
                                                                |
                                       Iabc, torque, theta, omega, BEMF
                                                                |
                           original Guest <- CMPSS0 <- U/V/W analog voltage
                                                  |
                                            ECAP1 / TIMG12
```

**No WFI breakpoints, no CPU stop, no GDB-driven plant stepping, no fixed artificial BEMF frequency.** All software-controlled and physical-simulation events advance on the shared QEMU Virtual Clock. Read-only diagnostics may sample but must never affect the model.

## Non-negotiable invariants

- Original Rel17.3 Guest ELF unchanged: `baseline/e62-g13b3/firmware/AM13E-rev17.3.elf` with SHA256 `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
- No Guest SRAM, IRQ, CAP1/TIMG12, MCPWM registers or commutation sequence writes by the host or model.
- Feed the motor from QEMU's original-clocked AQ/DB six-pad levels, gate state and Trip. Never substitute six-duty averages or guessed startup steps.
- Current continuity on phase switching, star constraints and explicitly modeled ideal-diode freewheel. Bounded integration and fail-closed invalid events or invalid physical values.
- Calculate electrical torque, mechanical speed and angle, and three-phase BEMF from the rotor model. Supply the three BEMF voltages through the CMPSS0 simulation analog interface on a native QEMU timer; no WFI wait or debugger intervention.
- Existing autonomous PA26 DShot timer may be reused. Rotor-derived BEMF and the preexisting synthetic autonomous BEMF generator must be mutually exclusive.
- Existing G14 (~20ns same-leg overlap) negative regression and G19 selected-input majority-filter rule remain. No Strict Gate waivers.
- The initial ECX87-KV147 profile is **SIM_ONLY, 24V, uncalibrated**. Not 12S, propeller, real board, MOSFET, GaN, thermals or physical hardware qualification.

## Stages and acceptance

1. **A: Native asynchronous plant wiring.** Add explicit opt-in motor component in QEMU, virtual-time physics timer, switching-event hook, source-generated BEMF, read-only counters, fail-closed state and mode arbitration. Ensure QEMU builds.
2. **B: Native Guest closed-loop source provenance.** Run unchanged Guest and autonomous PA26 DShot without CPU stops. Prove real PWM event → motor integration → real CMPSS filtered edge → original ECAP1 CAP1 → TIMG12 → next PWM sector.
3. **C: Physics verification.** Numerically compare continuous-current / diode behavior against the host reference, test energy and timestep convergence; do not tune to meet acceptance.
4. **D: Strict motor validation.** At least 12 original Guest CAP1/TIMG12/commutation sectors and 90ms, without significant rotor reversals; zero same-leg unsafe overlap, no missing PWM/gate provenance. A failed test remains failed.
5. **E: Board electrical and physical validation.** Actual BEMF sensing, propeller, driver, supply, protection, silicon timing and physical measurements remain OPEN.

## Historical evidence boundary

Previous WFI G20 diagnostics measured 35 WFI-bracketed model speed sign changes, including two before first accepted CAP1, and 23 significant post-six-sector reversals. Those values are historical diagnostic evidence **only**; they cannot certify an autonomous model. The previous 5ms startup early-capture hypothesis cannot be promoted to a validated root cause until the correct autonomous feedback timing is exercised.

## Development discipline

Commit directly to `main`, never use PR. Keep old host/WFI fixtures as clearly labeled historical comparators while implementing the new mode. Change of `machine/*.c` or `machine/*.inc` requires `./build.sh`, not just Python tests. No Host PASS may be represented as an original-Guest rotor stability PASS.

**Implementation status:** Incremental. Landing this document or source scaffolding is not itself evidence of a stable autonomous ESC–motor loop.


## Native no-WFI probe (opt-in, strict stability still OPEN)

Build the new machine from source and generate a SIM_ONLY ECX87-KV147
preboot configuration (the old archived QEMU binary predates this mode).
The `sim_motor_cfg.py` CLI intentionally requires **`g13b3` in the
output basename and a `.bin` extension**; use the dedicated name below.
Do not weaken this safeguard just to accommodate an incorrectly named file.

```bash
./build.sh
python3 tools/sim_motor_cfg.py --sim-only-opt-in \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --motor-profile ecx87-kv147 \
  --output artifacts/e62-g13b3-native-autonomous-cfg-flash.bin
python3 tests/e62_autonomous_native_motor_probe.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-native-autonomous-cfg-flash.bin \
  --artifact artifacts/e62-native-autonomous-smoke.json
```

The runner deliberately starts the original ELF *without* `-S`, GDB,
RSP, WFI stops, host PWM writes, or host BEMF injections. It stages
zero-throttle arm / fixed drive / zero-throttle recovery as real 1kHz
PA26 DShot600 wire events. The only live host operations are read-only
QTest status/diagnostics. The artificial timed-BEMF callback count
must stay zero; motor physics/analog feedback must advance independently.

**Scope warning:** a successful smoke only establishes QEMU source
wiring and autonomous feedback activity. It does not yet qualify
CAP1 geometric crossings, rotor stability, numerical convergence,
unmodeled physical driver behavior, or the original G20 strict gate.


### Failure diagnosis: first unqualified no-WFI smoke

The first user run with the correct G13B3 config succeeded in producing
the 336-byte original-ELF-derived Flash image, changing only
`telem_poles=14→42`. The no-WFI native probe then failed at the
combined source-clocked PWM / motor / analog activity predicate, which
did not identify which signal was absent. This is **NOT** a motor
stability outcome.

The probe now emits `E62_NATIVE_AUTONOMOUS_SOURCE_COUNTS` with:

- Autonomous PA26 capture/DMA counters, sent frames and stage.
- QEMU actual MCPWM4 zero/edge journal and AQ/DB validity.
- Native motor physics tick, actual-switch notification, analog
  publication, and fault counts.
- Read-only original Guest SRAM telemetry resolved from the **original
  ELF's** symbols, never by writing guest state.
- Bounded phase-transition snapshots and explicit failure reason codes.

On error, `E62_NATIVE_AUTONOMOUS_NO_WFI_FAIL` is printed and an
artifact retained. No acceptance condition or Motor Physics is
altered. This audit is asynchronous, cannot claim coherent
cycle-accurate cross-register snapshots, and does not block Guest CPU
or rely on any WFI instruction.

### Native current-sense / overcurrent safety integration

The first no-WFI smoke failed a compound motor activity gate. Source review
identified a real integration omission: earlier G13B2E/G13B4 fixtures wrote
three valid external current-sense ADC codes before enabling original Guest
OC/TZ. The new autonomous runner correctly does not fabricate them, but the
native motor originally produced only BEMF, leaving OC `oc_valid=false`.
The QEMU safety model intentionally interprets missing OC inputs as unsafe
when the original Guest selects Trip3; this can latch OST3 and prevent
actual PWM drive. **The smoke output did not contain enough individual
counters to prove this was the only failure.**

Native motor mode now drives actual model-derived three-phase OC codes,
including a model-zero-current reading before original Guest initializes
Trip routing, and updates those codes after PWM switch and rotor integration.
OC channels map W/V/U as defined in the existing simulated COMP mux, with
`code=1000+4*abs(phase_current_A)` explicitly **SIM_ONLY, not measured analog
amplifier calibration**. Values that exceed the 12-bit model range fail
closed. The existing Guest-defined DAC, comparator, XBAR, Trip2/Trip3, PWM
OST latch, and fault-clearing policies remain unchanged. External host OC
writes are rejected while Native Motor mode owns current sensing.

The no-WFI probe also reports per-stage read-only original Guest symbol
counters and QEMU PWM history validity, preserving distinct failure reasons
for insufficient DShot/Gate/PWM/physics/BEMF activity. It still does not
establish a strict G20 rotor-stability PASS.


### ELF duplicate static symbols (October 27)

The first extended no-WFI diagnostic runner aborted before launching
QEMU with `Duplicate original Guest ELF data symbol armed`. The
original Rel17.3 ELF legitimately contains file-static variables with
the same unqualified name. This is a **host telemetry resolver error**,
not a native motor dynamics, QEMU build, or Guest execution failure.

Optional original Guest SRAM diagnostics now admit only uniquely
addressed, real original-ELF symbols. Duplicated local symbols such as
`armed` are recorded under `unavailable_original_guest_diagnostics`
with `AMBIGUOUS_STATIC_ELF_SYMBOL`; the runner never selects an address
by sort order. Missing symbols are reported separately. The authoritative
MCPWM4 timer/history, PA26, native plant and CMPSS evidence remains
untouched. Unit negative-controls:
`python3 tests/test_e62_native_motor_guest_symbols.py`.

### No-WFI PA26/DMA receive-path isolation (2026-10-27)

An original-ELF native simulation transmitted **750** DShot frames and
observed **23,616** PA26 TIMG4 captures but only **32 DMA CH2 beats**.
Original Guest `valid_frame_feeds=0`, `throt=0`, `step=0`,
`calibration_done=0`, native MCPWM zero callbacks=0, rotor physics ticks=0.
The native motor **never started**, so these are not BEMF or rotor
stability measurements.

A 32-beat limit suggests one entire DShot receive-buffer transfer
occurred, after which the **Guest-owned** DMA/IRQ rearm pipeline did not
deliver subsequent packets. This is *not* proof of a DMA0 IRQ controller
defect, HardFault, or stale RX buffer, because the old snapshot omitted
DMA IRQ raw/mask, CH2 remaining/control and CPU exception state.

The updated no-WFI probe now samples existing QEMU read-only G11
architectural observer (PC/IPSR/PRIMASK/BASEPRI/FAULTMASK) and the real
DMA0 CH2 MMIO registers (IRQ mask/raw/masked, trigger, control, src/dst,
remaining). It also captures actual OC ADC sample validity and OST3
latch. All readings are asynchronous, non-atomic and **read-only**.
No CPU halt, WFI breakpoints, Guest memory writes, DMA reloads,
force-fed PWM, or synthetic BEMF are allowed.

A fail-closed receive classifier explicitly distinguishes an exhausted
first CH2 buffer from a pending DMA interrupt and a CPU Fault, instead
of claiming downstream PWM/BEMF missing is the primary defect.
Do not attempt physical rotor or strict G20 qualification until the
original Guest itself demonstrates valid physical DShot CRC input.
