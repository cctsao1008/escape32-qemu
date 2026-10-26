# E62 DShot300 — six-pad commutation and AM13E BEMF/VN review

## Datasheet/TRM conclusions (TI AM13E230x, SPRUJF2B section 22.3)

- CMPSS has a selectable **internal reference DAC** for the comparator's
  negative input. The external floating phase drives the positive input
  through the device's analog mux. The chip therefore does **not require a
  dedicated external VN pin** when this comparison configuration is used.
- **Physical external neutral, mathematical virtual neutral, fixed DAC
  threshold and VBUS/2 are NOT interchangeable.** An internal DAC does not
  itself measure VBUS/2; the firmware/board must choose a meaningful level.
- The target original Rel17.3 Guest actively configures CMPSS0 DAC and
  comparator routing, evidenced by the existing original-Guest CMPSS/ECAP
  functional runs. QEMU's `machine/am13e_motor_feedback.inc` computes
  comparison of the Guest-selected analog phase code against its **active
  Guest-owned DAC register**. The test must not program Guest CMPSS CSRs.
- No external VN signal is required in **this functional QEMU comparator
  front-end**. This is not a claim that an arbitrary physical ESC PCB has
  no neutral-sensing/reference circuitry.

## ADC review — explicitly NOT YET CONNECTED to simulated U/V/W

- `machine/am13e23019.c` G4b ADC0/1/2 sequencers latch external raw
  `channel_samples[channel]` on native SOC; default fixture is raw 2048
  for 32 channels per ADC, or `esc-sim-adc-fixture-file`.
- The CMPSS0 selected U/V/W input is separate from these ADC channels.
- There is **no verified original Rel17.3 ADC SOC-to-board-U/V/W mapping**
  in the examined SITL evidence. Do not guess ADC channels or silently
  route U/V/W voltages to current sense, DC-link, NTC or other SOCs.
- Until actual original Guest SOC channel registers plus board mapping
  identify a need, leave the ADC fixture untouched. Do not claim a
  `BEMF/VN -> ADC` qualification on this revision.

## Independent U/V/W functional generator (new)

`configs/e62-functional-bemf.json` selects a fixed electrical-frequency
three-phase *functional waveform*, not rotor physics:

`V_U = C + A sin(theta)`,
`V_V = C + A sin(theta - 120 degrees)`,
`V_W = C + A sin(theta + 120 degrees)`, in quantized 12-bit codes.

This signal **never** uses Guest selected_code, Guest active DAC, CMPSS
polarity or Guest current commutation step to choose its phase. The
`center_code` is a fixture parameter, not a claimed external VN pin.
Guest can accept, reject, or miss CAP1; no host timer, IRQ or Guest SRAM
forgery is permitted. The QEMU three SIM_ONLY analog words are written
while the original Guest is paused at a native WFI checkpoint; these
writes are sequential and **not yet certified as atomic analog commits**.

The default values (100 Hz electrical, -30 degrees, code center 2048 and
amplitude 128) are TEST STIMULUS settings. They do not represent ECX87
speed, motor Kv, prop load or a successful closed-loop tune.

## Six-pad functional oracle (new)

`--six-phase-audit` evaluates each observed source-owned Guest
`step` transition and corresponding original TIMG12 `serviced` count,
then samples all six QEMU MCPWM observer high-tick results. It requires
the next U_H/U_L, V_H/V_L, W_H/W_L source/return pair to match the
**pinned original Rel17 commutation table** independently of which
phase the Guest selected for BEMF comparator input.

- `commutation_wfi_bracket_ns`: previous and current Guest 16kHz
  SysTick-based **WFI observation bounds**, NOT exact TIMG12 ISR time.
- `pwm_settled_wfi_ns`: first observed settled expected pair,
  NOT the actual PWM compare edge timestamp.
- Read-only gate/pads/Trip/clock/power qualification required.
- Explicit transient carrier-zero interval is permitted until an
  evidence-preserving finite 750us cutoff; no wrong pair may be counted
  as a settled sector.
- Six distinct expected phase pairs, correctly ordered TIMG12/step
  transitions and zero accumulated issues qualify **WFI-bracketed
  functional six-phase** evidence only.
- Exact AQ/DB nanosecond edge chronology must be qualified separately
  via the existing `machine/am13e_pwm_history.inc` QEMU event journal
  and its bounded ring / dropped-event contract. Never convert WFI
  brackets to nanosecond edge timing or physical MOSFET measurements.

## DShot300 actual six-pad complementary PWM evidence (2026-10-26)

The 100-frame independent U/V/W native Guest trace showed 7 real Guest
TIMG12 services and **0** credited sectors in the first revision of
`FunctionalSixPhaseAudit`. The historical issue was an over-restrictive
oracle: it treated **any** nonzero source-leg complementary low-side
carrier duty as an extra independent sink.

The user's actual QEMU read-only six-output snapshots (channels ordered
`U_H,U_L,V_H,V_L,W_H,W_L`) show:

| Guest step | Expected source -> sink | Six high ticks | Period |
|---|---|---|---|
| 1 | W -> V | [0,0,0,4135,115,3988] | 4167 |
| 2 | U -> V | [115,3988,0,4135,0,0] | 4167 |
| 3 | U -> W | [152,3951,0,0,0,4135] | 4167 |
| 4 | V -> W | [0,0,190,3913,0,4135] | 4167 |

In Step 2, U_H=115 and U_L=3988 are **complementary modulation**,
while V_L=4135 is the sink and W_H/W_L=0 are floating. This is not two
independent low-side sinks. The source's PWM high/low deadband budgets
are consistent with the actual modeled high-tick counts:
`4167 - (115+3988) = 64` and `4167 - 4135 = 32`. This ratio is also
present in the other given steps. The QEMU hardware uses independently
delayed A-RED and B-FED; this is a **per-carrier average-high-tick
signature**, not measured instantaneous shoot-through deadtime.

`tools/functional_pwm_phase_match.py` now implements a strict,
separate original-six-pad pattern oracle:
- exactly one high-side source and a distinct near-full-carrier sink;
- floating third phase has both PWM outputs off;
- either legacy non-complementary source high with source low off, or
  a complementary source low with the appropriate 2x sink blanking
  budget; disallow unintended pad activity and invalid period sums;
- expected source/sink indices remain decoded from the pinned Rel17
  original commutation sequence, not from Guest-selected COMP phase.

`tools/functional_six_phase_audit.py` continues to require a genuine
Guest TIMG12 service, 1->2->3->4->5->6->1 sequence, native PWM Gate and
Trip qualification, and the existing **750us WFI settle window**. Its
failure evidence and incomplete bounded smoke status are not relaxed.
New matcher host-unit tests include the actual six-output vectors,
wrong-phase/float-pad/budget negative controls and original legacy
topology.

**The above real snapshots support the root-cause analysis; the changed
auditor itself still requires an actual QEMU re-run for Guest-backed
qualification.** Do not claim that the earlier 0-sector trace was a
PWM malfunction.

## DShot300 bounded regression experiment (not yet run on modified QEMU)

```bash
cd ~/github/escape32-qemu
git pull --ff-only
python3 -m unittest discover -s tests -p 'test_functional_pwm_phase_match.py' -v
python3 -m unittest discover -s tests -p 'test_functional_six_phase_audit.py' -v
python3 -m unittest discover -s tests -p 'test_functional_three_phase_bemf.py' -v

python3 tests/functional_dshot_sitl.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-functional-cfg-flash.bin \
  --plan scenarios/e62-dshot-v1.json --id T01 \
  --input-config configs/e62-functional-input.json \
  --bemf-config configs/e62-functional-bemf.json \
  --six-phase-audit --max-frames 100 \
  --artifact artifacts/e62-t01-dshot300-independent-bemf-sixphase-smoke.json

jq '{status,bemf_input_mode,external_vn_simulated,
    adc_bemf_channel_mapping_qualified,six_phase_audit,
    last_guest_state,stages}' \
  artifacts/e62-t01-dshot300-independent-bemf-sixphase-smoke.json
```

The 100-frame run intentionally ends with
`OPEN_BOUNDED_SMOKE_NOT_FULL_DURATION` and exits nonzero even when it
executes correctly. A functional phase auditor can separately report
`PASS_WFI_BRACKETED_SIX_PHASE_FUNCTIONAL_ONLY` only when actual Guest
TIMG12/PWM evidence covers a full six-step cycle. An independent
waveform can expose a real mismatch — the result is **OPEN/FAIL, never
fabricated PASS**. Existing DShot300 legacy-scripted full T01 PASS stays
separate and unchanged.

## Next strict boundary

- No real exact-resolution Guest TIMG12->MCPWM AQ/DB chronology pass yet.
- No verified Guest ADC SOC channel-to-phase-voltage or VN route yet.
- No real motor or physical shoot-through/gate-driver qualification.
