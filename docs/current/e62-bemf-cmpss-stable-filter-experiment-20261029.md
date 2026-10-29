# E62 — First Sensorless BEMF Robustness Improvement (2026-10-29)

## Scope / immutable source boundaries

Status **SOURCE-BUILT EXPERIMENTAL; NOT Original Rel17.3; NOT production-ready.**

The 2026-10-29 perturbation screen `#40817417417` using the exact
three-instruction Original-derived experiment found 2/8 non-SHA
motor/observability passes and 6 failures without waived criteria:

| Analog condition | direct20 | second profile |
| --- | --- | --- |
| 2us PWM-correlated transient `0:16` | PASS | gentle FAIL (6 reversals) |
| relative positive phase sense offset `16:0` | FAIL (244 reversals) | steps FAIL (162) |
| relative negative phase sense offset `-16:0` | FAIL (245 reversals) | ramp100 FAIL (58, no closed loop) |
| combined `16:20` | PASS | ramp500 FAIL (3 reversals) |

The analog offset is a *phase sense-to-fixed DAC relative error*,
not measured board VBUS or nominal control reference. In the model
the stationary 1.65V phase sense baseline shifts by +/-16 ADC codes,
while CMPSS DAC remains 2048. This distorts the phase-crossing
timing and cannot be rigorously fixed by copying a filter setting.
These input/source and original-analyzer failures are retained.

## Isolated firmware change: stable CMPSS digital filter

Experimental source **branch**:
`cctsao1008/ESCape32@experiment/e62-bemf-stable-filter-20261029`,
pinned source commit `73f48f3b0c89a984d3f74177fd6342c84f5c7e95`.
Control/candidate are built from **the same source commit**, with
the same Motor Output=1, reference seed 2048, 3ms startup and
`ival/4` policy, MCU/SDK and SIM_ONLY board electrical profile.
The **only** candidate addition is
`AM13E_SIM_ONLY_BEMF_STABLE_FILTER=1` in
`e62_sim_only_early_bemf_stable_filter.cmake`.

Source `mcu/AM13E/hal/motor_bemf.c`:
- Default comparator filter stays at `samplePrescale=0`,
  `sampleWindow=5`, `threshold=3` in initialization, and
  `(existing speed-band prescale,5,3)` after native interval select.
- The explicit experiment replaces both with
  `DL_CMPSSLITE_configFilterHigh(cmp,31,25,20)`.
- On QEMU modeled 200MHz MCLK: `20*(31+1)*5ns = 3.2us`
  of stable comparator input required. Synthetic switching
  transient duration is independently set to 2us in the physical
  source model. The TI SDK permits a 24-bit sample prescale,
  window up to 64, and threshold > window/2. QEMU currently uses
  a **bounded delay approximation**, NOT full silicon filter samples.
- **Original ECAP1 capture, CAP1 ACK, TIMG12 commutation
  scheduler, timeout, fault latch, dead-time, OC/Trip, nFAULT,
  Guest CRC and DShot frequency remain unchanged.**
- The filter setting is NOT a board noise measurement and not
  a full equivalent of STM32 TIM2 input capture filtering.

## Controlled A/B and strict gates

Workflow:
`.github/workflows/e62-experiment-source-built-bemf-filter-ab.yml`

It builds 2 source ELFs for each of direct20 and gentle, verifies
exact source commit and pinned TI SDK SHA, uses exact original JSON
DShot scenarios from 1kHz external FC, and runs each in:

1. Default analog source (`nominal`).
2. Independent QEMU physical switching disturbance (`0:16`).

It saves 4 separate source Guest executions per profile (8 total),
including whole-window rotor/current events and independent
Original P1 analyzer **expected** SHA rejection. The unchanged
`tools/native_p1_qualification.py` must return code 1 and include
`ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN` for both source-built
ELFs. All **other** original strict conditions must pass for
control nominal, filtered nominal, and filtered noise. The
control/noise negative case is preserved with its actual failures;
the candidate must show zero unwaived motor failures, otherwise this
experimental A/B job is RED. If the noise control **already has zero
reversals** (as happened in direct20), require strict no-regression:
zero candidate reversals and all source/ACK requirements PASS. This
is labeled `PASS_EXPERIMENTAL_NONREGRESSION`, NOT an improvement.
If the noise control has any reversals (as in the earlier gentle
pinned-ELF case), additionally require a strictly smaller candidate
reversal count and label only such a success as
`PASS_EXPERIMENTAL_IMPROVEMENT`. Additional
source-owned `E62_BEMF_STRESS_DIAG` events must prove that analog
noise was applied; these events are kept outside strict P1 event schema.

**No automatic pass from a green build.** No explicit transient
qualification means the experiment is inconclusive or fails.
An improved 2us noise test is NOT a solution to constant offset,
real board EMI, current sense, 47V/210KV propeller or formal P1.

## Next decision

1. If source-built filtered/noise results fail: compare the first
   `CMP_FILTER` transition, first genuine CAP1/ACK, TIMG12 and
   actual rotor torque reversal; do not adjust source model or P1
   thresholds until the failure is explained.
2. If the filtered/noise A/B passes: run the unchanged six-source
   nominal regression, then separately re-run all eight analog
   stress cases; offset tests are expected to remain open.
3. Evaluate board-calibrated VBUS/phase sense / DAC startup
   reference acquisition via the existing `AM13E_BOARD_SC5_CALIBRATION`
   design, and only then characterize real hardware. Do not
   hardcode new physical DAC codes without measured calibration.

## Raw temporal source trace (independently re-parsed 2026-10-29)

These are from archived **actual** `#40817417417` event-log ZIPs, not
inferences from the final CI status. `t=0` is the first **positive**
independent 1kHz DShot command; it is NOT the first powered PWM pair.

| Stimulus / scenario | First powered PWM pair | First CAP1 | First TIMG12 | First torque < -0.1 Nm | First rotor <= -50 RPM |
| --- | ---: | ---: | ---: | ---: | ---: |
| +16 ADC code / direct20 | 0.272ms | 12.546ms | 13.882ms | 5.966ms | 8.966ms |
| -16 ADC code / direct20 | 0.284ms | 4.011ms | 4.812ms | 7.209ms | 10.209ms |
| -16 ADC code / ramp100 | 0.284ms | **NONE** | **NONE** | 21.209ms | 26.209ms |
| 0:16 2us switching / gentle | 0.284ms | 0.285ms | 1.560ms | 157.210ms | 530.211ms |

Source `CMP_FILTER` transitions in the noisy direct20 trace:
29,912 total, of which 12,689 consecutive gaps were <3us.
In the noisy gentle trace: 80,861 transitions, of which 48,565
consecutive gaps were <3us. These counts demonstrate heavy
PWM-correlated comparator activity **in this QEMU model**, not a
measurement of actual EMI amplitude or a count of accepted CAP1.

- The **positive +16 offset** direct20 rotor exceeds -50 RPM
  **before the first CAP1**. Adding CAP1 digital debounce alone
  cannot retroactively fix such a fixed-sector overrun.
- The **negative -16 offset** direct20 already has genuine CAP1
  at 4.011ms and TIMG12 at 4.812ms, but still reverses at
  10.209ms. Simply increasing accepted-edge count is not proof of
  correct electrical phase/timing.
- The negative-offset ramp100 source never produces CAP1/TIMG12,
  so its gate failure is not a small perturbation of a healthy
  closed-loop execution.
- Switching-noise gentle first reaches <=-50 RPM only after
  ~530ms positive command. This may be a cumulative error or
  repeated spurious capture path, but timing correlation alone
  does not yet prove which exact CAP1 caused the reversal.

**Decision:** Do not combine fixed offset and switching transients
into a single firmware fix. Stable-filter A/B addresses only
short-duration switching transients. The offset track requires
actual phase-sense-to-DAC reference transfer calibration. No
invented static `2048 +/- 16` production recommendation is justified.

## CI compiler-only failure and correction

Initial source-built filter A/B [#40820236776](https://github.com/cctsao1008/escape32-qemu/actions/runs/40820236776)
stopped in the filtered **GCC -Werror=unused-variable** build:
the original speed-band `prescale` local became unused under
`AM13E_SIM_ONLY_BEMF_STABLE_FILTER`. The control image compiled.
The fix wraps the original local declaration in a conditional
compilation block; the code path remains unchanged for control.
New pinned firmware source commit:
`3ea4e672c0770db10c936531e7b3420b09473b18`.
The rerun is
[CI #40821482346](https://github.com/cctsao1008/escape32-qemu/actions/runs/40821482346).
The compiler-only failure is **not** a failed BEMF robustness
measurement. Do not claim the filter is effective until there is
an actual non-SHA mechanical PASS.

## Verified source-built A/B: genuine closed-loop data (2026-10-29)

[CI #40821992940](https://github.com/cctsao1008/escape32-qemu/actions/runs/40821992940)
has **completed successfully**. Both source-built jobs use EXACT
firmware source commit `3ea4e672c0770db10c936531e7b3420b09473b18`
and two distinct ELFs:

- **Control ELF SHA256**:
  `029043a46e186df26831c2de05cf9ac6145e7feec85f5dd12a31908424ec3899`
- **Filtered ELF SHA256**:
  `5b90b200429333cef82b982b7a7f845f31fb885c7ea63fc7e783c75232fac8d1`
- Original Rel17.3 SHA: `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`
  (**not** any of these source-built test Guests).

Independently downloaded `e62-experimental-source-cmpss-filter-gentle-NOT-P1`
artifact `12875326671`. The following per-case strict P1 JSONs
were read directly. Except for immutable Original SHA rejection,
all non-SHA P1 criteria were unwaived:

| Gentle trial | CMP_FILTER events | CAP1 Guest ACK | TIMG12 Guest ACK | Reversals >=50rpm | Peak SIM RPM | Non-SHA verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Control nominal | 3,387 | 2,234 | 2,234 | 0 | 493.820 | PASS diagnostic |
| Control 0:16 | 94,479 | 14,957 | 4,453 | 6 | 527.463 | FAIL significant reversal |
| Filtered nominal | 2,258 | 2,234 | 2,234 | 0 | 493.496 | PASS diagnostic |
| **Filtered 0:16** | **2,416** | **2,234** | **2,233** | **0** | **493.094** | **PASS diagnostic** |

All four cases preserve source QEMU motor physics, independent
flight controller's exact 1kHz wire schedule, fault routing, and
unchanged Original P1 checker. The **filtered/noise** row has 36
source-diagnostic stress events independently proving physical source
perturbation before CMPSS. No Host-written Guest CAP1/IRQ.

The reduced simulated CMP_FILTER event rate (94,479 -> 2,416)
is strong evidence that the majority filter rejects the injected
short switching artifacts. The approximately unchanged model
peak speed and 0 reversals support a bounded improvement in
this one model / scenario. **Not** evidence of board noise immunity
or 47V real motor performance.

For direct20, all four A/B cases preserve zero reversals and the
unaltered non-SHA strict gates; **non-regression** is the only
justified classification. A control already at 0 reversals cannot
be numerically improved below zero.

### Larger matrix, separate verification

[Full matrix workflow #40823411978](https://github.com/cctsao1008/escape32-qemu/actions/runs/40823411978):
seven parallel job groups, one byte-exact pinned filtered source ELF,
six unchanged nominal scenarios and eight untouched analog stress
cases (14 Guest runs). The existing `tools/native_p1_qualification.py`
and all strict non-SHA criteria remain intact; any source Guest
reversal or missing CAP1/TIMG12 ACK is kept as RED. The
`tools/experimental_e62_source_bemf_filter_matrix.py` must refuse
ELF SHA drift, fabricated source stress, missing physical evidence,
or an Original P1 identity waiver. **Results not yet asserted here.**

## Final fourteen-case pinned source-built result (#3)

The corrected [CI #40865298408](https://github.com/cctsao1008/escape32-qemu/actions/runs/40865298408)
**completed** on the exact stable-filter source-built ELF SHA
`5b90b200429333cef82b982b7a7f845f31fb885c7ea63fc7e783c75232fac8d1`.
The workflow has an overall red status because **six legitimate
model-level motor/observability gates failed**, not because QEMU,
firmware build, or configuration failed. All seven job groups saved
artifacts, including strict Original-P1 SHA rejection.

| BEMF analog condition | Scenario | Source CAP1 ACK | TIMG12 ACK | Reversals (>=50RPM) | Diagnostic non-SHA |
| --- | --- | ---: | ---: | ---: | --- |
| nominal | smoke | 1540 | 1540 | 0 | PASS |
| nominal | gentle | 2234 | 2233 | 0 | PASS |
| nominal | direct20 | 2742 | 2742 | 0 | PASS |
| nominal | steps | 2112 | 2112 | 0 | PASS |
| nominal | ramp20_100ms | 1905 | 1904 | 0 | PASS |
| nominal | ramp20_500ms | 2321 | 2320 | 0 | PASS |
| `0:16` switching noise | direct20 | 2741 | 2741 | 0 | PASS |
| `0:16` switching noise | gentle | 2235 | 2234 | 0 | PASS |
| `16:0` reference bias | direct20 | 232 | 232 | 233 | FAIL reversal |
| `16:0` reference bias | steps | 169 | 168 | 169 | FAIL reversal |
| `-16:0` reference bias | direct20 | 234 | 234 | 234 | FAIL reversal |
| `-16:0` reference bias | ramp20_100ms | 0 | 0 | 44 | FAIL reversal, closed loop, missing comparator transitions |
| `16:20` combined | direct20 | 232 | 232 | 233 | FAIL reversal |
| `16:20` combined | ramp20_500ms | 0 | 0 | 0 | FAIL missing closed loop and comparator transitions |

**Totals: 8/14 bounded simulated motor PASS; 6/14 FAIL.**
A zero-reversal case is **not** a PASS if CAP1/TIMG12
never establish closed loop. The strict Original Rel17.3 SHA gate
remains intentionally failed on all these source-built Guest trials;
Original P1, real board, propeller and product qualification remain
false. No test thresholds, model motor torque, fault semantics or
DFC source signals were relaxed.

The previous G13B3 SIM_ONLY CFG output basename issue
[issue #2](https://github.com/cctsao1008/escape32-qemu/issues/2)
was fixed in commit `e6942d211452ce4ba24695ebbd5c50a32373dcf5`
and closed independently of the real robustness failures.

### Follow-on relative-reference causality experiment (#4)

Existing `ESCape32` firmware contains a physical-board calibration
structure with separate per-phase ADC gain/offset, comparator correction
and DAC offset fields, plus an opt-in source-managed ADC measurement/
DAC publication path. No actual board electrical coefficients are
known, and `AM13E_BEMF_INITIAL_DAC_CODE=2048` is only the initial
**SIM_ONLY** reference model.

To test the limited *relative reference bias* hypothesis, source-built
GitHub Actions
[#40867595824](https://github.com/cctsao1008/escape32-qemu/actions/runs/40867595824)
compares unchanged `2048` control with separately compiled,
explicitly non-flash synthetic `2064` and `2032` DAC variants,
under unchanged corresponding `+16:0` and `-16:0` physical source
perturbations. QEMU motor plant, DShot fixtures, electrical fault
enforcement and strict Original P1 analyzer remain the same.
The experiment records whether closed-loop CAP1/TIMG12 and zero
significant reversals *recover* under reference alignment;
it does not establish a physically measured E62 board coefficient
and is not a release-qualification shortcut. If alignment does not
restore the closed loop, another mechanism must be diagnosed.

## Reference-bias source-built causal A/B — +16 PROVEN IN MODEL

[CI #40877818256](https://github.com/cctsao1008/escape32-qemu/actions/runs/40877818256)
`+16` source-built Guest job successfully completed. The identical
PT_LOAD image check anchors the control to the prequalified stable
filter reference image, using independently calculated SHA256
`8e8eb3472bfee51711d93e333b0dba52d649a1acc6c01376e9e66503f42499e2`.
Control and matched versions differ at only physical address
`0xC190`: `0x00 -> 0x01` corresponding to initial SIM_ONLY DACH
`2048 -> 2064`; **every other loadable byte is the same**.
Complete ELF hashes are retained separately; nonloaded ELF metadata
is not a hardware-instruction difference.

| Offset +16 | Control DACH 2048 | Matched DACH 2064 |
| --- | ---: | ---: |
| direct20, significant reversals | 233 | **0** |
| direct20, CAP1/TIMG12 guest W1C ACK | 232 / 232 | **2742 / 2742** |
| steps, significant reversals | 154 | **0** |
| steps, CAP1/TIMG12 guest W1C ACK | 154 / 154 | **2170 / 2170** |
| non-SHA complete motor observability | FAIL both | **PASS both** |

The QEMU physical BEMF analog stress source applied the same
`+16:0` perturbation in both cases, with source-owned diagnostic
events present. Original P1 identity rejection remains active for
both experimental Guest versions; no Guest register writes, no
synthetic timed BEMF, no WFI/GDB. This demonstrates a **bounded
relative-reference mismatch causal mechanism in the modeled
sensorless startup**, not real board calibration or 12S qualification.

The independent `-16` source-built job also passed in
[#40877818256](https://github.com/cctsao1008/escape32-qemu/actions/runs/40877818256):
`direct20` control reference 2048 produced 234 significant reversals
and 234 CAP1/TIMG12 ACKs; matched synthetic reference 2032 produced
**0 reversals and 2741 CAP1/TIMG12 ACKs**. For `ramp20_100ms`,
control produced 43 reversals and **0 CAP1/TIMG12 ACKs**;
matched produced **0 reversals and 1911 CAP1/TIMG12 ACKs**.
Both matched cases passed **all non-SHA** P1 motor observability gates.
Independent PT_LOAD proof anchored to the exact prequalified control
image showed one loaded byte changed at `0xC190`:
`0x00 -> 0xFE`. No input, plant, or P1 gate changes.

**Joint causal result:** all four pure ±16 model bias scenarios fail
with an uncompensated 2048 reference and pass with a model-matched
reference, while preserving original Guest SHA rejection and real
QEMU motor/ECAP/TIMG12 feedback. This identifies fixed relative
reference bias as a model-level *sufficient causal mechanism*.
It is not a demonstration of production ADC/DAC transfer accuracy.

The subsequent independent
[#40879428785](https://github.com/cctsao1008/escape32-qemu/actions/runs/40879428785)
adds combined `+16:20` offset and 2us switching-source noise to
`direct20` and `ramp20_500ms`, with unchanged filter and physical
source to verify whether both mitigations are jointly sufficient.
Its results must be judged separately and cannot be inferred
from these four pure-offset scenarios.

The synthetic DAC seed is not the runtime SC5 calibrated
ADC→VBUS→phase sense→DACH publication pathway and must not be
promoted to a production `AM13E_BEMF_INITIAL_DAC_CODE` constant.

## Combined offset+switching stress with reference aligned (#3/#4)

[Source-built A/B CI #40879428785](https://github.com/cctsao1008/escape32-qemu/actions/runs/40879428785)
**completed SUCCESS for all three jobs** (pure ±16 and joint
`+16:20`). On the latter, real source-owned 2us switching transients
were active concurrently with static +16 sense bias. The physical
analog perturbation diagnostics contain **36 source events each**
for both controls and matches, with actual nonzero noise codes.

| Combined +16:20 stress | Control DAC 2048 | Matched DAC 2064 |
| --- | ---: | ---: |
| direct20 rotor reversals | 233 | **0** |
| direct20 CAP1 / TIMG12 Guest ACK | 232 / 232 | **2742 / 2742** |
| ramp20_500ms rotor reversals | 0 | **0** |
| ramp20_500ms CAP1 / TIMG12 Guest ACK | **0 / 0** | **2321 / 2321** |
| all unwaived non-SHA motor/observability gates | FAIL | **PASS** |

**Zero rotor reversal is insufficient**: ramp500 control has 0
reversals but **no genuine hardware feedback**; it is a real FAIL.
The matched ELF differs by only the audited SIM_ONLY DACH seed byte
(`2048 → 2064`), preserving the same source-built 31/25/20 CMPSS
filter, independent DShot source, QEMU analog plant/perturbation and
unaltered Original P1 negative SHA gate. This is **joint
model-level causality**, not a calibrated AM13E board.

### SC5 source-code reference-epoch negative gate (#4)

The native FW experimental branch
[ESCape32 commit b6d0c6c](https://github.com/cctsao1008/ESCape32/commit/b6d0c6cd959f5f0f7da2fbe0410ff40343bd611)
now rejects incomplete/zero-identity ADC reference epochs before
calculating/publishing a BEMF reference. The pure C
`am13e_bemf_reference_fresh()` requires a nonzero completed sample
and *each* of the unsigned modular elapsed intervals
acquisition→completion, completion→now and acquisition→now to remain
within the explicitly configured maximum age (including legitimate
32-bit SysTick wrap). No board transfer coefficients were invented.

[Host CI #40885636881](https://github.com/cctsao1008/ESCape32/actions/runs/40885636881)
**SUCCESS**, both optimized `-Werror` and UBSan executions,
including negative tests for incomplete scans, future/old time stamps,
identity-zero and expiry boundary; existing numeric SC5 calibration
and 4096-input ADC normalization tests also pass. This is **unit
evidence** only, not an AM13E ADC ISR or PWM-synchronized DACH
publication integration test.

### Independent second-demand experiment (#5)

[Source-built CI #40886338291](https://github.com/cctsao1008/escape32-qemu/actions/runs/40886338291)
exercises an unchanged, pinned stable-filter source ELF with
a **new separate** 1kHz DShot schedule:
1500ms neutral → 1500ms 20% → 1500ms neutral/coast →
1500ms 20% → 300ms neutral.

An independent source-time oracle verifies separately that EACH
powered window contains ≥12 real Guest PWM_PAIR/CAP1_ACK/TIMG12_ACK,
no significant reverse rotor response, and positive ≥50rpm
response, plus no active motor events after 200ms settle in the
intermediate coast interval. It must reject borrowed first-demand
ACKs, corrupted DShot, sustained coast energization, and false
claims of full standstill. The strict original P1 analyzer stays
unchanged; source-built Guest must remain SHA-rejected as
`ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN`.
**No physical standstill restart, hardware, or release qualification
is asserted from this new test.**

## Source-built oldstep versus cold-sector second-demand causal A/B (#5)

[CI #40892524402](https://github.com/cctsao1008/escape32-qemu/actions/runs/40892524402)
**completed SUCCESS** on two separately compiled exact experimental
ARM Guests, driven by the SAME 6300 frames of genuine 1kHz DShot600
and the same 24V uncalibrated ECX87 KV147 QEMU physical motor model.

The control deliberately retains the actual Rel17 `laststep()`
sector memory `oldstep`, restored at the next start; its
PT_LOAD fingerprint is identical to the earlier source-built
filtered firmware:
`8e8eb3472bfee51711d93e333b0dba52d649a1acc6c01376e9e66503f42499e2`.
The cold-sector candidate alone enables the explicitly
nonflashable `AM13E_SIM_ONLY_EXPERIMENTAL_COLD_RESTART=1` guard,
choosing `step=0` before the original `nextstep()`. This
**does not measure electrical rotor position**, and is a
mechanism-isolation test only.

| Window source observation | Original oldstep restore | SIM_ONLY cold-sector |
| --- | ---: | ---: |
| First 20% demand, negative rotor samples ≤−50RPM | 0 | 0 |
| First demand CAP1 / TIMG12 Guest ACK | 2742 / 2742 | 2742 / 2742 |
| Second 20% demand, negative rotor samples ≤−50RPM | **5** | **0** |
| Second demand PWM_PAIR | 2734 | **2741** |
| Second demand CAP1 / TIMG12 Guest ACK | 2734 / 2734 | **2740 / 2740** |
| Neutral/coast, active motor events ≥200ms after neutral start | 0 | 0 |
| Original P1 identity acceptance | Rejected | Rejected |
| Original P1 non-SHA motor gate | FAIL rotor reversal | **PASS** |
| Independent per-demand oracle | FAIL | **PASS** |

This source-owned A/B supports the conclusion that **reusing
the stale commutation sector across a long neutral/coast is a
significant contributor** to this specific second-start rotor
reversal. It does not demonstrate that forcing sector 1 is
universally safe for an arbitrary rotor phase or windmilling
direction; no production behavior is changed.

The next bounded no-waiver regression is
[coast duration CI #40894919388](https://github.com/cctsao1008/escape32-qemu/actions/runs/40894919388):
300ms coast (significant retained spinning likely) and
3000ms coast (near stop), each with paired oldstep control
and cold-sector Guest. These source scenarios are independent
of motor readiness, retain the original strict P1 negative SHA
gate and preserve all non-SHA failures as **red**, including
unexpected motor energization in neutral/coast.

## Cold-sector coast sensitivity and physical torque diagnostic (2026-10-29)

The [300ms/3000ms coast sweep #40894919388](https://github.com/cctsao1008/escape32-qemu/actions/runs/40894919388)
fully executed both original source-built `oldstep` and strictly
SIM_ONLY cold-sector restart variants (unchanged source model,
6300/5100/7800-frame independent external-FC commands as applicable,
strict source identity). **Overall CI RED is correct**:
- 300ms coast: **oldstep FAIL 9 negative ≥50RPM samples**;
  **cold-sector FAIL 6**.
- Prior 1500ms coast: oldstep FAIL 5; cold-sector PASS 0.
- 3000ms coast: **oldstep FAIL 7; cold-sector PASS 0**.
All cases retained Guest CAP1/TIMG12 evidence, original P1 SHA
rejection, and complete motor trace. A zero capture regression
cannot be called PASS, nor can a start with transient reversal.

A separate [read-only artifact-replay CI #40905207362](https://github.com/cctsao1008/escape32-qemu/actions/runs/40905207362)
**SUCCESS** regenerated machine-readable initial rotor-state
evidence from the unmodified archived source-generated motor traces.
It also passed six positive/negative source parser unit tests in
[#40905206962](https://github.com/cctsao1008/escape32-qemu/actions/runs/40905206962).
The replay tool uses QEMU's documented model-internal `ROTOR`:
`a=milliRPM`, `b=milliradians unwrapped electrical angle`,
`f=micronewton-metres actual modeled torque`. These fields
**are NOT inputs readable by the running firmware**; they are
strictly read-only diagnostic information.

| Coast | Experimental Guest | Pre-second-demand RPM | QEMU model electrical phase | First torque | First new CAP1 | Negative ≥50 RPM first 20ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 300ms | original oldstep | +8.058 | 237.63° | **−0.165 N m** | 7.350ms | **9 — FAIL** |
| 300ms | cold-sector | +8.376 | 247.08° | **−0.127 N m** | 1.434ms | **6 — FAIL** |
| 3000ms | original oldstep | +1.010 | 312.02° | **−0.314 N m** | 8.319ms | **7 — FAIL** |
| 3000ms | cold-sector | +1.010 | 312.02° | **+0.215 N m** | 4.105ms | **0 — PASS** |

The *first* torque polarity change under cold-sector
(negative at shorter coast; positive at longer coast) is a
direct source-owned model observation; it is NOT proof of a
particular HW DAC calibration or startup controller design.
The two coast intervals change both electrical phase and
residual mechanical RPM, so the present sweep does **not**
independently isolate phase versus speed. At 300ms the
control and cold candidate also have slightly different
pre-restart states, so avoid a false claim of exact state
equality within that pair.

**Decision:** `AM13E_SIM_ONLY_EXPERIMENTAL_COLD_RESTART` remains
a restricted diagnostic, NOT a production fix. Without a
qualified rotor-phase/windmilling-acquisition mechanism,
an arbitrary blind commutation sector cannot demonstrate
guaranteed forward torque from every initial angle.
A viable hardware program must validate the phase
observation or bounded current-limited alignment/start
contract and test both CW/CCW and physically loaded cases;
neither Original P1 nor customer hardware readiness changes.

## Native passive BEMF code observability during coast (#5)

The independent read-only [passive coast BEMF audit #40907076649](https://github.com/cctsao1008/escape32-qemu/actions/runs/40907076649)
**SUCCESS**; its seven positive/negative source tests also PASS.
It replays the four *unaltered* QEMU native model
`E62_P0_EVENT BEMF_FRONTEND` traces from the actual prior
[300/3000ms motor sweep #40894919388](https://github.com/cctsao1008/escape32-qemu/actions/runs/40894919388).
This telemetry contains three ADC-like BEMF codes from the QEMU model,
**not a proven MCU-accessible, pinmux-validated passive voltage measurement**.
Neither the tool nor the Guest reads QEMU's true rotor angle, speed or torque.
The source 1kHz external FC DShot frames, negative strict Original P1 SHA,
coast zero-output condition and sample-ordering validity remain checked.

All four cases had **at most 1 LSB phase-to-phase code contrast** over
the final 100ms before restarting after either 300ms or 3000ms of coast.
A 3-code threshold is used **only as an illustrative diagnostic floor**
greater than a one-code quantization ambiguity; it is **not an
actual board ADC noise figure, hysteresis or customer qualification gate**.
Even higher model contrast cannot establish phase sequence/direction
without an authenticated hardware input route and multiple consistent
phase crossings. All cases therefore set
`passive_model_signal_qualified_for_rotor_angle=false`,
`board_ADC_route_qualified=false`, `firmware_enable_granted=false`.

Actual 50ms QEMU source BEMF contrast maxima during early coast:

| Neutral age | Model max U/V/W code contrast |
| --- | ---: |
| 0–50ms | 131–137 |
| 50–100ms | 15 |
| 100–150ms | 6 |
| 150–200ms | 2 |
| 200–250ms | 1 |
| 250–300ms | 1 |

Model mechanical dynamics/friction and analog scaling remain
**uncalibrated relative to the actual EC87 KV210 / 47V / APC 24×12E
motor/propeller/board**. The relative decline nevertheless demonstrates
why windmill direction detection must be attempted in a suitably
observable regime instead of assuming a BEMF zero crossing survives
all the way to a very slow second start.

**Blocked product question:** no qualified low-speed rotor-phase
acquisition exists for the blind re-demand region. Source-built
`oldstep` produces reverse torque; SIM_ONLY cold-sector also fails
300ms coast. None of those sectors is a safe substitute for a validated
passive phase/direction observer or a separately bounded, gate-safe
current-limited rotor alignment/start strategy. No source code may
arm the hardware from QEMU model-internal ground-truth angle.
#5 stays open.

## Passive three-phase voltage-order alias gate (#5)

The existing AM13E firmware DOES have `adc_latest.phase_a/phase_b/phase_c`
from the sequential ADC0/ADC1/ADC2 software-triggered scan, and a
coherent `am13e_app_adc_get_raw()` API. That should NOT be confused
with a calibrated/synchronized passive windmilling observer or a
proven real-board phase-voltage wiring route. The actual
`BEMF_FRONTEND` QEMU debug telemetry is sampled at a different
**1kHz source-diagnostic cadence**; it is **not** evidence that the
hardware ADC is limited to 1kHz.

The strictly read-only
[phase order CI #40913885732](https://github.com/cctsao1008/escape32-qemu/actions/runs/40913885732)
**SUCCESS** with 7 host negative/positive tests and four original
motor artifact replays. It ranks the native source's three ADC-like
voltage codes into six distinct U/V/W relative permutations, with an
illustrative >=2-code per-adjacent-level separation, and refuses
to claim actual rotor phase or release motor outputs.

| Coast interval | Oldstep: nonadjacent rank changes | Cold-sector: nonadjacent rank changes |
| --- | ---: | ---: |
| First 100ms of 300ms coast | **2** (27 total changes) | **2** (26 changes) |
| First 100ms of 3000ms coast | **2** (27 changes) | **2** (27 changes) |

Those skipped rank transitions are evidence that a **1ms QEMU
telemetry snapshot does not preserve a guaranteed full adjacent
phase-state sequence**, *not* evidence of a genuine motor reversal.
A real windmill detector would require measured phase sequence,
sampling rate, analog noise/hysteresis, phase gain/offset/reference,
IRQ timing and physical sensorless motor characterization. Any
inference from QEMU model-internal rotor angle/speed/torque is
forbidden as a shortcut to guest firmware.

The distinct [coast code-contrast CI #40907076649](https://github.com/cctsao1008/escape32-qemu/actions/runs/40907076649)
already demonstrated ≤1 ADC-like code of phase contrast in the
last 100ms before re-demand for all cases. Hence both early
sampling alias risk and late analog unobservability remain #5
design blockers. Neither `oldstep` nor blind `step=0` is a
general, approved solution.

## Original Guest modeled safety retention (#7)

The **running, no-WFI** source-built Original Rel17.3
[CI #40907619582](https://github.com/cctsao1008/escape32-qemu/actions/runs/40907619582)
**SUCCESS**:
- Actual external PA22 nFAULT asserted at frame 2100, released
  at frame 2300; hard source OST2 remained latched, output Gate
  safe-off and no automatic rearm; strict zero-failure audit.
- Separate 2800-frame external DShot hard-loss source test passed
  strict Guest WWDT BOOTRST with 2679 firmware feed writes
  and no observed model deadline error.

A separate current-branch **neutral/WFI/GDB** fault-routing
[CI #40913109969](https://github.com/cctsao1008/escape32-qemu/actions/runs/40913109969)
**SUCCESS** for physical-model `nfault` plus
`oc-u`, `oc-v`, `oc-w`, each through OST2/OST3
latch→Original MCU interrupt `IPSR=44`→native shutdown.
The strict four-fault matrix reports zero errors and intentionally
sets `MODEL_ONLY_NATIVE_NEUTRAL_NOT_MOTOR_RUNNING`.

**DO NOT CONFLATE:** three-phase neutral OC/IRQ tests do **not**
establish no-WFI **running** OC protection; and even running
nFAULT/DShot model passes do **not** establish real MOSFET/GaN
driver, 12S, physical current comparator or fault propagation
latency. Issue #7 stays OPEN for real running OC and board
electrical/thermal safety evidence.
