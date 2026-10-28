# E62 — FW Porting SITL Verification Matrix

**Scope:** AM13E23019, Original ESCape32 Rel17.3 firmware, pinned ELF
SHA-256 `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
**Purpose:** quantify porting integration evidence in absence of product hardware.
Not a claim of semiconductor timing accuracy, motor/propeller qualification or
full application functional compliance.

## Verification lanes (keep separate)

**Track A — FW Porting SITL:** Original Guest executes unmodified. Verify
actual QEMU register behavior, Guest MMIO, NVIC, DMA, DShot, physical
six-pad AQ/DB and derived timer event chronology. Real source events and
strict fail-closed contracts are required; unsupported aspects remain open.

**Track B — Motor Dynamics:** Uncalibrated current-continuous ECX87 147KV
24V, zero propeller load, idealized analog. This evidence can demonstrate
*source connectivity* but cannot certify propeller startup, physical
analog thresholds or a customer 47V/210KV system. Frozen P1 direct20
and steps remain RED; do not waive or substitute slow ramp tests.

| ID | Porting requirement | Evidence and source | Status and limitation |
|---|---|---|---|
| A01 | Pinned original Guest ELF/Vector boot | SHA identity and source-built QEMU No-WFI Run #40557926065 | **VERIFIED_SIM_ONLY** for frozen image; not a physical boot |
| A02 | PA26 externally sourced DShot, DMA, CRC, Guest receiver | Run #40557926065, 3000/3000 external frames, 2380 original valid-frame feeds | **VERIFIED_SIM_ONLY** for this scenario; not signal integrity |
| A03 | Clock/SysTick / NVIC and IRQ dispatch | No-WFI probe and source P0 tests #40557926125 | **PARTIAL**; not cycle-accurate silicon latency |
| A04 | MCPWM source AQ/DB / six-pad chronological carrier outputs | First source PWM_PAIR and physical switch events from P0 strict #40557926125 | **VERIFIED_SIM_ONLY** for modelled events; not MOSFET switching or dead-time scope |
| A05 | CMPSS0 rising/falling filter -> ECAP1 actual CAP1 and NVIC | Source CMP_FILTER/CAP1/CAP1_ACK in archived P1 #40557926101 | **VERIFIED_SIM_ONLY** for enabled route; actual analog frontend **HW_REQUIRED** |
| A06 | Guest reads CAP1 timestamp, original ISR acknowledges | Source-built P0 #40631864428 + strict archived MMIO replay #40632866806 matched **824/824** real CAP1→Guest ACK→Guest CAP1 MMIO reads | **VERIFIED_SIM_ONLY_P0**; ACK/read do not establish Guest algorithm acceptance |
| A07 | Guest writes TIMG12 PERIOD/START/STOP after CAP1 and exact virtual timer zero | Source-built P0 strict replay #40632866806 matched **824** Guest TIMG12 START→actual virtual ZERO, max absolute deadline error **2ns** | **VERIFIED_SIM_ONLY_P0** virtual register/timer contract; not silicon jitter |
| A08 | TIMG12 ZERO -> Guest ACK -> next actual PWM pair | New P0 source #40631864428 and all-timer replay #40632866806; 824 TIMER ZERO and Guest ACK; existing strict P0 source causal chain gate PASS | **VERIFIED_SIM_ONLY_P0** for guest-programmed timer and causal order; not every P1 startup profile |
| A09 | Source closed-loop, no host Guest writes/WFI/GDB/synthetic BEMF | P0 strict #40557926125 and independent motor run #40557926065 | **VERIFIED_SIM_ONLY** for P0, not all throttle profiles |
| A10 | Safety: real nFAULT / OC / shoot-through / gate disable | Dedicated CI and source models are available, but no fresh integrated safety verdict here | **PARTIAL / HW_REQUIRED** |
| A11 | ADC physical current/VBUS/NTC calibration and analog mapping | `docs/current/esc-functional-bemf-pwm-review.md` explicitly lists ADC SOC U/V/W mapping unverified | **NOT_VERIFIED / HW_REQUIRED** |
| A12 | Physical MOSFET, ECX87 210KV, 47V, APC 24x12E load/propeller dynamics | Current SIM_ONLY plant is ECX87 147KV, 24V, no propeller | **HW_REQUIRED**, not an E62 porting acceptance gate |
| A13 | Guest early BEMF acceptance policy | Original Rel17.3 `ival=10000`; `capture < ival/2`. New P1 MMIO trace #40631864594: first CAP1 ACK+READ has **no timer rearm** in direct20/steps; second CAP1 ACK+READ **does** rearm TIMG12 | **SOURCE_CODE_VERIFIED; MMIO_DECISION_CONSEQUENCE_OBSERVED**; internal return/branch not directly observed |
| A14 | P1 accelerated startup stability | New source-built P1 #40631864594: smoke/gentle PASS (0/0), direct20/steps FAIL (337/223 reversals), with valid MMIO timing and unchanged `STARTUP_SIGNIFICANT_DIRECTION_REVERSAL` | **TRACK_B_SIM_ONLY_FAIL_UNWAIVED** |


## Verified original-Guest P0 register-timing ledger (2026-10-28)

- Frozen P0 source run [#40631864428](https://github.com/cctsao1008/escape32-qemu/actions/runs/40631864428): **PASS_NATIVE_P0_STRICT** and archived original QEMU source-event file. Original unmodified ELF is pinned; QEMU built from this same machine source. No WFI/GDB host Guest-register writes or synthetic BEMF.
- Read-only archived P0 full replay [#40632866806](https://github.com/cctsao1008/escape32-qemu/actions/runs/40632866806): **PASS_SOURCE_MMIO_P0_SIM_ONLY**, zero reported contract issues; **824/824** matched physical CAP1 + Guest IRQ ACK + actual CAP1 register read; **824/824** matched Guest TIMG12 START→actual QEMU-clock virtual TIMER ZERO; maximum absolute timer deadline residual **2ns**.
- Source events include **825** `T12_LOAD` and `T12_START` but **824** TIMER ZERO within finite trace; the replay validates every *observed* ZERO, and does not treat an unfinished recording tail as a physical timeout. This is not evidence of an application-level accepted/rejected BEMF decision.
- Every deadline uses actual Guest MMIO period, clock and epoch counter, rather than a host computed motor speed or inferred commutation delay. The 2ns bound is **virtual-time consistency only**, not real AM13E timer tolerance.
- New pinned-trace replay lives at `tools/native_porting_mmio_p0.py`, guarded by `tests/test_native_porting_mmio_p0.py` and `.github/workflows/e62-porting-p0-mmio-source-replay.yml`. The source artifact remains available independently of each future source-only regression.
- The high-speed P1 direct20/steps first-CAP1 acceptance question is **not** established by P0. P1 analysis `native_porting_mmio_chain.py` still needs its original failing-case trace and must retain the existing red P1 verdict.


## Verified Original Guest P1 MMIO evidence (2026-10-28)

Fresh source-built [strict P1 #40631864594](https://github.com/cctsao1008/escape32-qemu/actions/runs/40631864594) retains its **unchanged** four-case motor verdict: smoke PASS, gentle PASS, direct20 FAIL, steps FAIL. The **separate porting MMIO diagnostic** analyzed all four actual original Guest traces and returned `PASS_MMIO_SOURCE_CONTRACT` for each, with **0ns** difference between first real TIMG12 one-shot Guest START virtual deadline and QEMU TIMER ZERO.

| P1 scenario | Guest CAP1 ACK + READ | TIMER re-armed after first CAP1? | Second CAP1 action | MMIO Contract | P1 Motor Dynamics |
|---|---|---|---|---|---|
| smoke | Yes | Yes | n/a | **PASS** | **PASS**, 0 reversals |
| gentle | Yes | Yes | n/a | **PASS** | **PASS**, 0 reversals |
| direct20 | Yes | **No** | Second ACK + READ followed by TIMER START | **PASS** | **FAIL**, 337 reversals |
| steps | Yes | **No** | Second ACK + READ followed by TIMER START | **PASS** | **FAIL**, 223 reversals |

The first direct20 CAP1 occurred **2.3488ms** after first powered PWM pair, second at **10.8968ms**, and first actual TIMG12 ZERO at **13.4590ms**. The steps first CAP1 occurred **2.39184ms** after first physical powered pair; second **10.94084ms**. These are read-only source timestamps in one QEMU virtual clock.

This demonstrates that the first fast CAP1 was *physically captured, IRQ-acknowledged and read by the Original Guest*, but did **not** cause a Guest TIMG12 timer re-arm before the next capture; the second did. This is consistent with the Original Rel17 `ival/2` minimum capture interval. The MMIO trace does **not** directly expose Guest-local `capture_us`, `ival`, or `bemf_zero_cross_delay()` return value; do not label an internal reject branch as directly observed.

[Read-only P1 MMIO source replay #40633019199](https://github.com/cctsao1008/escape32-qemu/actions/runs/40633019199) **PASS**. The workflow explicitly requires the unchanged P1 motor **FAIL** for direct20 and steps while validating separate Peripheral Porting MMIO **PASS**. The archived red P1 result remains red.

## Exact provenance added without changing firmware/physics

- `ECAP1_CAP1_READ`: real Guest 32-bit CAP1 register read (value, contemporaneous
  ECAP counter, ECFLG/ECEINT/ECCTL2). Does **not** assert accepted crossing.
- `T12_LOAD`: real Guest TIMG12 LOAD write (ticks, native Hz, current mode).
- `T12_START`: real Guest one-shot timer START (load, Hz, epoch counter, mode, IRQ mask).
- `T12_STOP`: real Guest stop/cancel of timer (last counter, old load/mode).
- Existing `CAP1`, `CAP1_ACK`, `TIMG12`, `TIMG12_ACK`, `PWM_PAIR` continue unchanged.
- Analysis computes expected true virtual ZERO = start_virtual_time +
  ceil(remaining_ticks*1e9/native_hz). An actual ZERO without the correct
  source-programmed deadline **fails** the MMIO source contract.
- An ACK followed by CAP1 read with **no** TIMG12 START before another capture
  means only **no re-arm observed**. The Guest's private accept/reject return
  value is not exposed; do not label it confirmed reject.

Strict P0/P1 logic and thresholds are unchanged. The new diagnostic's
"PASS_MMIO_SOURCE_CONTRACT" is a **porting observer result only**, not P1
acceptance; P1 startup reversals remain genuine SIM_ONLY FAIL.

## Execution and follow-through

1. `.github/workflows/e62-porting-mmio-contract.yml` lightweight source
   contract PASS [#40631902642](https://github.com/cctsao1008/escape32-qemu/actions/runs/40631902642).
2. Source-built P0/P1 workflows rebuild QEMU from source after `machine/**`
   changes. `.github/workflows/e62-native-p1.yml` retains unchanged
   strict four-case suite and exports
   `artifacts/e62-p1-scripted/e62-porting-mmio-chain.json` even when
   P1 fails.
3. Inspect per-case CAP1 → ACK → Guest CAP1 read → timer load → start →
   actual zero → Guest ACK → physical PWM pair; compare actual MMIO
   timing with pinned Guest source code.
4. A06–A08 are **VERIFIED_SIM_ONLY_P0** by 824 matched MMIO read/timer
   events; strict read-only four-case **P1 MMIO** replay also PASS, but its
   separate motor-dynamics acceptance **remains RED** on direct20/steps.
   All HW-dependent claims remain open.
