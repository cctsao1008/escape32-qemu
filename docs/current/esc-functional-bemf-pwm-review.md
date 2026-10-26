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

## Latest native independent U/V/W six-pad WFI proof (2026-10-26)

The user-supplied `e62-t01-dshot300-independent-bemf-sixphase-smoke.json`
after the strict complementary-output oracle correction showed:

- 100 externally delivered DShot300 frames; the outer bounded
  scenario status correctly remained `OPEN_BOUNDED_SMOKE_NOT_FULL_DURATION`.
- `PASS_WFI_BRACKETED_SIX_PHASE_FUNCTIONAL_ONLY`;
  `settled_commutation_count=7`, `failed_commutation_total=0`,
  `issues=[]`.
- All **six** pinned original source/sink pairs:
  U->V, U->W, V->W, V->U, W->U, W->V.
- Every settled six-pad image was
  `COMPLEMENTARY_SOURCE_H_L_AND_SINK_L`, QEMU MCPWM4 period 4167.
- Several original-step/WFI brackets contain an old six-pad vector and
  a new vector within the SAME Guest 16kHz SysTick. It is therefore
  incorrect to assign exact physical or even QEMU PWM edge times to
  `pwm_settled_wfi_ns`.

This closes WFI-bracketed **functional** six-step topology validation only,
not exact callback chronology or full T01 duration.

## Opt-in next step: actual QEMU PWM virtual-clock event history

The existing 128-record QEMU event ring at `0x5ffe7000` emits
`QEMU_CLOCKED_AQ_DB_EDGE`, original carrier-ZERO callbacks and
Guest MMIO/shadow/trip markers. New
`tools/functional_pwm_clocked_trace.py` reads this **on every genuine
running-loop Guest WFI** after original zero-throttle ARM. It:

- preserves exact **global QEMU virtual ns** from actual callbacks, no
  extrapolated/synthetic edges;
- preserves separate **Guest SysTick-relative ns** from original ELF;
- refuses to align those two clocks without independent correlation;
- fails closed on ring overwrite between consecutive WFI stops, mixed
  masks, model invalidation, storage overflow or internal same-phase
  H/L both-high masks;
- never claims physical MOSFET/deadtime measurement or rotor physics;
- does not recover any pre-attach history.

`--clocked-pwm-history` requires `--six-phase-audit`, and is not
available with `--autonomous`. The default opt-in bounded host memory
limit is 100000 events, which is intended for a **100-frame smoke**, not
the 11-second or 110-second full sequence. Larger histories are
explicitly bounded with `--clocked-pwm-max-events`; no silent
truncation is permitted. Existing T01/T02 without the flag remain
unchanged.

```bash
cd ~/github/escape32-qemu
git pull --ff-only
python3 -m unittest discover -s tests -p 'test_functional_pwm_clocked_trace.py' -v

python3 tests/functional_dshot_sitl.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-functional-cfg-flash.bin \
  --plan scenarios/e62-dshot-v1.json --id T01 \
  --input-config configs/e62-functional-input.json \
  --bemf-config configs/e62-functional-bemf.json \
  --six-phase-audit --clocked-pwm-history \
  --max-frames 100 \
  --artifact artifacts/e62-t01-dshot300-clocked-pwm-smoke.json

jq '{
    status,
    six_phase_status: .six_phase_audit.status,
    clocked_pwm_history: (.clocked_pwm_history | {
      status, collected_wfi, collected_events,
      qemu_clocked_edge_callbacks, original_pwm_zero_callbacks,
      unsafe_internal_both_gates_high_masks,
      qemu_pwm_invalid_model_events_since_attach,
      missed_ring_events, collection_error,
      first_events, last_events
    })
  }' artifacts/e62-t01-dshot300-clocked-pwm-smoke.json
```

The modified Guest-backed clocked-history runner is **OPEN until actually
executed**. Host unit tests with mock QEMU historical ABI data cannot
substitute for that run. Even a successful trace qualifies QEMU
internal callback chronology, **not** real hardware gate timing.

## Guest-backed QEMU clocked history 100-frame PASS (2026-10-26)

The user actually executed `--clocked-pwm-history --six-phase-audit`
with independent U/V/W and physical-format DShot300. The saved JSON
reports:

- outer test: `OPEN_BOUNDED_SMOKE_NOT_FULL_DURATION` (100 frames);
- `PASS_WFI_BRACKETED_SIX_PHASE_FUNCTIONAL_ONLY`;
- `PASS_QEMU_CLOCKED_INTERNAL_PWM_HISTORY_ONLY`;
- 6,869 records collected on genuine native Guest Running-WFI stops,
  comprising 3,632 `QEMU_CLOCKED_AQ_DB_EDGE` callbacks and 1,215
  `QEMU_ORIGINAL_PWM_ZERO_CALLBACK` records;
- zero in-scope missing ring events; zero internal same-leg H/L
  simultaneously HIGH masks; zero model-invalid events; no collection
  error;
- the collected journal begins at record sequence 1258 after arming:
  **prior QEMU records are outside this qualification scope**.

Observed ZERO #301 at global QEMU virtual timestamp 13,769,005,288 ns
and ZERO #1515 at 13,870,184,484 ns. Their interval divided by
1,214 periods is ~83,343.65 ns per carrier, approximately **11.9985
kHz** in this observed simulator run. This is a measurement of **QEMU
callback timing**, not a requested ESC switching-frequency specification
or a physical hardware PWM frequency qualification.

Clocked event timestamps are global QEMU virtual ns; Guest Step and
`observed_guest_elapsed_ns` are **WFI observation context**, not the
instant Guest TIMG12 serviced. Do not claim exact ISR-to-edge latency
without a shared timestamp domain and IRQ event marker. The history
tracks internal QEMU AQ/DB outputs, not physical gate voltage.

### Next run: 11-second independent U/V/W functional T01

Run full T01 with `--six-phase-audit` **but without**
`--clocked-pwm-history`. The latter stores every event; the 100k
default record limit is unsuitable for the full-duration 11-second
trace and should not be silently truncated.

```bash
set -o pipefail
python3 tests/functional_dshot_sitl.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-functional-cfg-flash.bin \
  --plan scenarios/e62-dshot-v1.json --id T01 \
  --input-config configs/e62-functional-input.json \
  --bemf-config configs/e62-functional-bemf.json \
  --six-phase-audit \
  --artifact artifacts/e62-t01-dshot300-independent-bemf-full.json \
  2>&1 | tee artifacts/e62-t01-dshot300-independent-bemf-full.log

jq '{
  status,completed_full_duration,external_input_protocol,
  bemf_input_mode,dshot_frames_sent,stages,teardown,
  six_phase_audit: (.six_phase_audit | {
    status,settled_commutation_count,failed_commutation_total,
    all_six_guest_steps_observed_with_expected_pwm,issues
  }),issues,last_guest_state
}' artifacts/e62-t01-dshot300-independent-bemf-full.json
```

The full 11-second independent-frequency BEMF acceptance remains
**OPEN** until genuine Guest execution completes all stage/neutral and
six-phase oracles; the preceding 11-second *Guest-directed scripted*
BEMF PASS is a separate experiment.

## Full independent three-phase DShot300 T01 PASS (2026-10-26)

The user executed **unmodified original Rel17.3 ELF** in the non-autonomous
per-WFI QEMU functional runner, with external DShot300, 100 Hz independently
generated U/V/W analog inputs and strict source-pinned six-pad PWM oracle.
Real user-provided final evidence:

- `status = PASS_FUNCTIONAL_INDEPENDENT_THREE_PHASE_BEMF_ONLY`
- `completed_full_duration = true`
- 11 seconds of virtual Guest scenario time: 1s 0->90% ramp, 10s 90% hold
- `dshot_frames_sent = 11000`; increment of original Guest CRC-feed
  counter observed within stages: ramp 883 + hold 8697 = **9580**,
  **not** a per-frame 100% verified delivery claim.
- Ramp: original Guest CAP1 delta **85**, TIMG12 service delta **84**;
  all six steps seen; stage PASS.
- Hold: original Guest CAP1 delta **858**, TIMG12 service delta **857**;
  all six steps seen; stage PASS.
- `PASS_WFI_BRACKETED_SIX_PHASE_FUNCTIONAL_ONLY` with **941** settled
  original TIMG12/step-linked six-pad sectors, **0** unsettled sectors,
  all six source/sink patterns and `issues=[]`.
- Genuine DShot300 neutral teardown: one physically scheduled neutral frame,
  CRC valid-feed increased, original `throt=0`, `armed=0`, teardown
  **62500 ns** excluded from the scenario duration.
- The final original Guest counters were
  `valid_frame_feeds=9582`,
  `captured_events=943`, `scheduled=943`, `serviced=941`.
  They are different counters with different semantics; do not assert
  every external frame was decoded or every captured event serviced.

### Acceptance boundary: phase tracking remains unqualified

The independent U/V/W analog source remains the fixed-frequency
`configs/e62-functional-bemf.json` **100 Hz electrical** test fixture.
Ideal coherent sensorless six-step switching at 100 electrical Hz
would produce approximately **600 sector advances per second** after
lock. Actual HOLD **857 services / 10 seconds = 85.7 sector advances
per second**; its equivalent nominal six-step cycle rate is
**~14.28 electrical cycles/s**, *not* the 100 Hz stimulus rate.

The full T01 PASS proves the original Guest runs through valid, powered,
source-pinned six-pad commutation with independently supplied phase
signals for the full scripted DShot envelope. It does **NOT** establish
phase lock, speed tracking, voltage/zero-crossing detection precision,
real motor stability or correct mechanical RPM. A future strict
correlation experiment must compare Guest accepted BEMF/CAP1 time,
Guest selected floating phase and source-pinned expected edge with the
**independent electrical phase clock**, using an honestly correlated
timebase; it must not alter BEMF to follow Guest commutation.

The preceding **100-frame** `PASS_QEMU_CLOCKED_INTERNAL_PWM_HISTORY_ONLY`
is separately qualified; full-duration T01 did not enable that
high-volume history collector. Neither pass qualifies physical gate
driver timing, shoot-through, motor current, external VN or ADC SOC
phase-voltage mapping.

## Next strict boundary

- No real exact-resolution Guest TIMG12->MCPWM AQ/DB chronology pass yet.
- No verified Guest ADC SOC channel-to-phase-voltage or VN route yet.
- No real motor or physical shoot-through/gate-driver qualification.
