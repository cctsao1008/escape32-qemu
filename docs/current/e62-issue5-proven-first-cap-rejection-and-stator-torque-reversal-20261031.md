# E62 Issue #5 — First CAP1 Rejection and Fixed-Stator Torque Reversal: Source-Proven QEMU Causal Chain

**2026-10-31 | SIM_ONLY, Original ESCape32 Rel17.3 ELF unchanged, strict Original P1 unchanged, Issue #5 remains OPEN.**

## Executive finding

In the current QEMU motor-only startup experiment, **there is no need for a reversed ESC PWM command, reversed PWM phase order, or inverted BEMF wiring to produce mechanical rotor reversal**:

1. The immutable ESCape32 Rel17 algorithm starts six-step with `ival=10000us`. Its genuine source BEMF policy rejects `capture_us < ival/2`, i.e. initially **less than 5000us**. This is deliberate early/spurious-crossing rejection, not QEMU IRQ starvation.
2. The first genuine `CMP_FILTER -> CAP1 -> CAP1_ACK -> ECAP1_CAP1_READ` source event is indeed handled, but **no `T12_LOAD` / new commutation schedule follows it**. The second `CAP1` passes the acceptance filter and **replaces the previously armed 65,535us startup timeout** with a 2,436–2,640us one-shot. Actual TIMG12 callback then occurs on the expected 100MHz peripheral clock.
3. The actual fixed six-pad power pair stays **W positive / V negative / U floating** (native `PWM_PAIR=8`, source mask 24). The QEMU first-sector rotor accelerates from -30° electrical pose across the magnetic equilibrium, where **the very same winding currents switch from positive to negative electromagnetic torque**. No change in digital phase order is necessary.
4. The QEMU *model rotor* then decelerates and reverses BEFORE the second physical PWM power pair, while the firmware still waits for an accepted capture and delayed commutation. The simulated motor parameters (rotor-only J, uncalibrated phase current / driver, BEMF gain, no-prop load) are not physical hardware qualification.

This establishes the **source-consistent cause of reversal within the current QEMU plant and unchanged firmware policy**. It does **not** establish that either part is a product defect on physical hardware.

## Immutable provenance

- Original firmware SHA-256: `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
- [24V 100MHz source run #41178267331](https://github.com/cctsao1008/escape32-qemu/actions/runs/41178267331), KV210 Original Guest source artifact.
- [47V 100MHz source run #41109233164](https://github.com/cctsao1008/escape32-qemu/actions/runs/41109233164), KV210 no-prop source artifact.
- [24V/47V 200MHz A/B #41178746233](https://github.com/cctsao1008/escape32-qemu/actions/runs/41178746233), both with QEMU actual 200MHz root clock confirmed by source readback.
- 5,100 real QEMU DShot source frames per run: 1500 neutral, 1500 positive 20%, 300 neutral, 1500 positive 20%, 300 neutral. No Guest SRAM write, synthetic CAP1, invented rotor angle input, WFI/GDB patch or Original P1 waiver.

## Two captures and genuine one-shot timer

| KV210 no-prop profile | 1st CAP1 after first positive command | 2nd CAP1 after command | Startup initial T12 one-shot | T12 replacement after 2nd CAP1 | Actual 1st next power pair |
|---|---:|---:|---:|---:|---:|
| 24V, QEMU 100MHz | 2.684ms | 12.412ms | 65,535µs | 2,638µs | 15.118ms |
| 24V, QEMU 200MHz | 2.652ms | 12.384ms | 65,535µs | 2,640µs | 15.055ms |
| 47V, QEMU 100MHz | 2.105ms | 9.178ms | 65,535µs | 2,436µs | 11.701ms |
| 47V, QEMU 200MHz | 2.094ms | 9.173ms | 65,535µs | 2,438µs | 11.617ms |

All times above are relative to first original QEMU DShot +20% command. Each first CAP1 has matching source `CAP1_ACK` and `ECAP1_CAP1_READ`, so the hardware event was not simply lost. **The absence of a new T12 schedule after the first capture and its presence immediately after the second event establish precisely where the long wait occurs.**

### Independent integer inversion of the immutable firmware's scheduling arithmetic

Firmware `src/main.c::bemf_zero_cross_delay()`:

```c
if (capture_ticks < (ival >> 1)) return 0;
int u = ival * 3;
ival = (capture_ticks + u) >> 2;
return max((ival - (ival * cfg.timing >> 5)) >> 1, 1);
```

The original Guest provisioned flash Cfg used by all four source jobs has **cfg.timing=16** (Cfg byte offset 24), `sine_range=0` (offset 25). On initial six-step startup `ival=10000us`. The accepted second CAP1 schedules via TIMG12 on independent 100MHz BUSCLK with `period_ticks = 100*delay_us-1`. Invert the actual source `T12_LOAD.a` through these exact integer expressions; with the 200MHz ECAP1 timestamp difference between the two captures, infer the first rejected capture interval:

| Source profile | Accepted second-capture interval implied by actual T12 period | ECAP1 capture timestamp delta | Inferred first-capture interval |
|---|---:|---:|---:|
| 24V/100MHz | 12,204–12,219µs | 9,728µs | **2,476–2,491µs** |
| 24V/200MHz | 12,236–12,251µs | 9,732µs | **2,504–2,519µs** |
| 47V/100MHz | 8,972–8,987µs | 7,073µs | **1,899–1,914µs** |
| 47V/200MHz | 9,004–9,019µs | 7,079µs | **1,925–1,940µs** |

In *every* source case the inferred **first event is strictly under 5000µs and rejected**, while the second is over 5000µs and schedules the actual commutation. These are deterministic inverse ranges, **not direct reads of the Guest's private `ival` or `crossing_epoch` variables**. Exact integers depend on the pinned Original Rel17 policy and Cfg image. The QEMU-observed TIMG12 source `T12_START -> TIMG12` interval matches the replacement 2,436–2,640µs, i.e. **no evidence of a QEMU CPU insufficiently fast to service this timer**.

Firmware audit sources:
- [Rel17 `bemf_zero_cross_delay` and `am13e_app_motor_on_bemf_event`](https://github.com/cctsao1008/ESCape32/blob/am13e-port-v2/src/main.c)
- [Native `ECAP1_IRQHandler` and early-edge reject handler](https://github.com/cctsao1008/ESCape32/blob/am13e-port-v2/mcu/AM13E/hal/motor_bemf.c)
- [Native 100MHz `TIMG12` `schedule_us`](https://github.com/cctsao1008/ESCape32/blob/am13e-port-v2/mcu/AM13E/hal/motor_event_timer.c)

## Rotor reverses because electromagnetic torque depends on electrical angle

The source model uses phase offsets U=0°, V=-120°, W=+120° and `T=K_phase*sum(I_phase*sin(theta+phase_offset))`. During the first unchanged source `PWM_PAIR=8`, the high side is **W** and low side is **V**, with `I_W≈-I_V>0` and `I_U≈0`; therefore the motor model reduces approximately to:

```text
T ≈ Kt_terminal * I_W * cos(theta_e)
  ≈ 0.0454 (N·m/A) * I_W (A) * cos(theta_e)
```

The model initially starts near **theta_e=-30°**. Under the same fixed stator field, torque is positive while `cos(theta_e)>0`, crosses zero at **theta_e=90°**, and becomes negative for `theta_e>90°`. That is **negative *mechanical* electromagnetic torque with physically unchanged positive/negative phase connections**.

Actual 200MHz QEMU `ROTOR` source records:

| Motor | Rotor electrical angle | U/V/W source current | Logged source torque | Analytic fixed-pair torque |
|---|---:|---|---:|---:|
| 24V KV210 | +45.3° | 0 / -35.637 / +35.637 A | **+1.139 N·m** | +1.139 N·m |
| 24V KV210 | +97.2° | 0 / -55.164 / +55.164 A | **-0.310 N·m** | -0.313 N·m |
| 47V KV210 | +45.2° | 0 / -82.731 / +82.731 A | **+2.648 N·m** | +2.646 N·m |
| 47V KV210 | +121.9° | 0 / -125.748 / +125.748 A | **-3.011 N·m** | -3.019 N·m |

Small differences reflect the rounding/serialization of electrical angle and phase currents. The same source `PWM_PAIR` persists through these positive and negative torque samples. The **source rotor subsequently changes sign before the next digital power pair**, establishing genuine model angular overshoot rather than reversed command signaling.

The model's motor-only inertia is `J=0.00013 kg m²` from the ECX87 rotor data, `Kt_terminal=0.0454 N·m/A`, `R_phase=0.0283ohm`, `L_phase=8.75µH`, with fixed idealized diode/freewheel and 1.65V + 0.02×BEMF uncalibrated phase ADC assumption, and **no physical propeller attached**. Those assumptions make startup acceleration, currents (roughly 36–126A at the records above) and electrical-angle overshoot dependent on model fidelity.

## Decision and precise next action

**Confirmed within QEMU:** The sequence is (1) original 20% step directly into six-step (Cfg `sine_range=0`), (2) first valid BEMF CAP1 handled but **rejected by unchanged `ival/2` early-edge policy**, (3) lack of commutation during accelerating model rotor, (4) rotor goes past theta_e=90° while W/V current direction stays unchanged, (5) same currents yield negative electromagnetic torque, braking and rotating rotor backward, (6) second CAP1 finally accepted and 100MHz timer schedules the next real six-step power pair.

**Not proven:** That firmware acceptance policy is defective in real hardware; that the 24V/47V QEMU rotor acceleration and phase current reflect a real ESC; or that the user must modify any firmware. No P1 waiver or test-specific logic injection is allowed.

**Recommended engineering resolution path:** Before changing code, obtain a measured real motor unloaded/prop-equipped current and electrical rotor speed/BEMF timing for a *matched* low-throttle startup, including first physical CAP1 and first PWM commutation, then calibrate model inertia, drive/freewheel current and analog BEMF. The same Original P1 must rerun on independently calibrated source models. A genuine firmware early-edge / startup-ramp change requires separate physical validation and release qualification rather than tuning it simply to pass SITL.

The **11–15ms delay mechanism and simulator torque-reversal mechanism are now both source-explained**. **Issue #5 remains OPEN** until qualified startup/restart behavior is demonstrated. **No code/firmware change is justified solely to achieve a green CI.**
