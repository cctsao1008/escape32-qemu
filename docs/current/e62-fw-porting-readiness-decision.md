# E62 — Firmware Porting SITL Readiness Decision (2026-10-28)

## Decision

**Bounded SITL FW-porting evidence is PASS for the tested original Guest /
QEMU peripheral chain. Overall FW porting and physical ESC qualification
are NOT signed off.** Do not require an uncalibrated unloaded motor plant
to pass every rotor-acceleration scenario before evaluating the verified
MCU peripheral implementation. Also do **not** declare an application
functional PASS based on source-MMIO consistency alone.

The independently produced [six-source readiness evidence packet](https://github.com/cctsao1008/escape32-qemu/actions/runs/40640025195)
was generated **successfully** from actual archived, source-built Guest
runs and is available as the GitHub Actions artifact
e62-fw-porting-readiness-frozen-original-guest-packet
(JSON and Markdown). It is **frozen**, not a fresh simulated flight and
not an assertion that every present branch source was retested. The
aggregate machine-readable status is:

PASS_BOUNDED_SITL_PORTING_EVIDENCE_WITH_OPEN_ITEMS

Explicit fields remain:
- porting_complete = false
- hardware_qualified = false
- motor_p1_all_cases_qualified = false
- guest_capture_reject_private_return_observed = false
- acceptance thresholds not waived, original Guest ELF not changed

## Evidence scope and decision boundary

| Track | Actual source evidence | Decision and limitation |
|---|---|---|
| A: Original Guest no-WFI and P0 | [P0 #40631864428](https://github.com/cctsao1008/escape32-qemu/actions/runs/40631864428); [P0 MMIO replay #40632866806](https://github.com/cctsao1008/escape32-qemu/actions/runs/40632866806) | PASS for source QEMU timing and original Guest control of modeled peripheral |
| A: Original CAP1/ECAP/TIMG12 | 824 original CAP1 + Guest ACK + read; 824 Guest TIMG12 START→ZERO, max error 2ns QEMU virtual | PASS for hardware-model MMIO contract, **not** AM13E silicon clock jitter |
| A: Actual P1 event-chain behavior | [P1 MMIO #40633019199](https://github.com/cctsao1008/escape32-qemu/actions/runs/40633019199) from [original P1 #40631864594](https://github.com/cctsao1008/escape32-qemu/actions/runs/40631864594) | Four MMIO source checks PASS. Fast first CAP1 read causes no observed rearm, second CAP1 causes rearm. Private return value unseen |
| A: DShot physical wire CRC | [valid/bad CRC #40631864430](https://github.com/cctsao1008/escape32-qemu/actions/runs/40631864430) | PASS original callback/WWDT valid feed and bad CRC rejection. **CRC alone** does not verify command loss; this fixture uses WFI |
| A: No-WFI DShot active hard loss | [source #40639394403](https://github.com/cctsao1008/escape32-qemu/actions/runs/40639394403) | PASS: FC stops at 2,800 frames; 2,189 actual Guest WWDT feeds; source-owned WWDT→BOOTRST at 1s, 0ns virtual mismatch, model PB13 LOW/PWM safe-off; real LFCLK/reset recovery unqualified |
| A: Peripheral boundary regression | [QEMU source-built #40639899206](https://github.com/cctsao1008/escape32-qemu/actions/runs/40639899206) | PASS G6/G7/G10/G13B2/G5/G14 timer/DMA/CMPSS/ECAP/Trip/WWDT negative contracts, **model-only QTest** not running Guest |
| A: Neutral fault routing | [OC U/V/W and nFAULT #40631864426](https://github.com/cctsao1008/escape32-qemu/actions/runs/40631864426) | PASS modeled Trip latch, original MCPWM4 IRQ, shutdown. **Neutral motor state**, not running loaded prop |
| A: In-flight physical nFAULT | [No-WFI PA22 fault #40631864583](https://github.com/cctsao1008/escape32-qemu/actions/runs/40631864583) | PASS modeled OST2 latch and six-pad gate safe-off. No automatic re-arm or recovery certified |
| B: Startup physical dynamics | [strict P1 #40631864594](https://github.com/cctsao1008/escape32-qemu/actions/runs/40631864594) | smoke/gentle PASS; direct20/steps **FAIL** (337/223 reversals). Never waived |
| Extended functional input/feedback | [T02 #40631864440](https://github.com/cctsao1008/escape32-qemu/actions/runs/40631864440) | PASS 110000 frames with **scripted functional BEMF**; explicitly **not** physical rotor/loaded motor qualification |
| Historical pinned G13B3 pairing | [exact historical drift #40633710369](https://github.com/cctsao1008/escape32-qemu/actions/runs/40633710369) | Source fingerprint mismatch **remains open**. Separate archived binary-byte-integrity CI PASS does not make current source match historical binary |

### Historical G13B3 source fingerprint — unchanged strict failure

The read-only diagnostic established **5** changed fingerprint entries
compared with the archived G13B3 binary manifest:

1. build.sh
2. machine/am13e23019.c
3. machine/am13e_motor_feedback.inc
4. machine/am13e_pwm_history.inc
5. machine/am13e_trip_safety.inc

This is sufficient to explain why the existing tool
tools/e62_pinned_baseline.py verify rejects the **archived binary +
current source** as a valid historical build pair. It is not evidence
that today's freshly compiled native QEMU necessarily contains a bug.
Do not rehash/republish an old baseline, rewrite its manifest or silence
the historical regression to obtain a green CI.

The separate source-built original Guest P0/no-WFI and exact MMIO tests
are the authoritative *current-source SITL integration* evidence.

## Confirmed causal observation, not firmware defect proof

In direct20 and steps the original Guest acknowledges and reads the
first physical CAP1; no subsequent TIMG12 START is observed before the
second CAP1. After the second capture, Guest TIMG12 LOAD/START occurs,
and the actual hardware-model ZERO matches the Guest-armed one-shot.

This matches the original firmware startup minimum-half-interval
capture filter. It does not directly observe the guest-local
capture_us/ival or the return of bemf_zero_cross_delay(). Model rotor
acceleration and physical propeller load remain uncalibrated. No
change to startup threshold, motor torque, inertia or BEMF is authorized
by this diagnosis alone.

## Remaining requirements before full product signoff

- Physical silicon clock/IRQ latency, CMPSS reference DAC and filter
  thresholds, and ECAP capture routing with actual board signals.
- ADC SOC-to-board VBUS/phase-current/temperature channel mapping and
  calibration under board electrical tolerances.
- Actual gate-driver/deadband/MOSFET, bus-voltage protection, nFAULT
  and overcurrent trip and temperature rise.
- Real motor/propeller inertia and load; verify customer motor profile,
  47V condition, startup, acceleration, controlled shutdown.
- Physical DShot electrical signal integrity, real LFCLK/WWDT period,
  hardware reset cause, post-fault recovery/re-arm and field protection
  remain open. No-WFI SIM_ONLY Original Guest loss-of-command BOOTRST
  is **verified**, separately from real board qualification.
- Original Guest release provenance, board-qualified release and
  production programming/debug flow.

## How to reproduce the readiness snapshot

- Read-only aggregation: tools/e62_porting_readiness.py.
- Negative test contract: tests/test_e62_porting_readiness.py.
- Six-source workflow: .github/workflows/e62-porting-readiness-packet.yml.
- P1 closure and negative scope: docs/current/e62-p1-porting-sitl-closure.md.
- Original full source verification matrix:
  docs/current/e62-fw-porting-verification-matrix.md.
- Exact archive diagnostic:
  tools/e62_pinned_source_drift_report.py and
  .github/workflows/e62-pinned-source-drift-diagnostic.yml.

Artifacts have a **21-day retention period**. Replaying the frozen
snapshot after the artifacts expire must fail closed, not silently
fall back to untracked sources or a new behavior model. For a later
release candidate, record a new self-consistent source-built run and
re-pin the six source artifact run IDs together; never mix guest,
hardware model, thresholds or QEMU source without disclosing it.
