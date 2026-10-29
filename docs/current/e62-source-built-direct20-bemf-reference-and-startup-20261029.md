# E62 AM13E: source-built Direct20 no-reversal reproduction (SIM_ONLY)

**2026-10-29:** Completed SIM_ONLY source-build control/candidate A/B.
Direct20 1.5s no-significant-reversal is demonstrated in **raw QEMU
ROTOR events**. This is *not* the immutable Original Rel17.3 P0/P1
qualification, product/HW qualification or safe-to-flash approval.

## 1. Independent control and candidate

CI [#40805581044](https://github.com/cctsao1008/escape32-qemu/actions/runs/40805581044) was **SUCCESS**. Artifacts:
`e62-early-cap1-direct20-exp-not-original-guest` (ID 12868651028)
include both built ELFs, 3300-frame source logs and comparison JSON.

Both Guests were built from the same ESCape32 experimental source
commit `d467ab4b35fdf1a0996680649498004e23f52001` with identical
MOTOR_OUTPUT_CONFIGURED=1 QEMU-only board fixture, and use the same
QEMU ECX87 KV147 corrected phase model, input stages and config.
Control does not set `AM13E_SIM_ONLY_EXPERIMENTAL_EARLY_BEMF`;
candidate does. Candidate enables:
- Startup interval initially **3000us** rather than Original 10000us.
- Early BEMF crossing acceptance **ival/4** rather than Original
  `ival/2`.

Original pinned ELF SHA256
`05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`
has **not** been changed or replaced.

## 2. Why the previously source-built motor was fault-latched

The earlier SIM_ONLY source-build path required Motor Output 1, but its
control entered `runtime_fault` during motor start. Read-only
firmware-instrumented SRAM snapshots proved:
- `e62_sim_runtime_fault_reason=6`:
  `am13e_motor_output_start()` returned 0.
- `e62_sim_motor_output_start_reject=3`:
  `am13e_app_motor_bemf_reference_start_ready()` returned false.
- Pre-fault state 0x04: safety initialized, fault not latched.
  This rules out an existing fault latch before the failing start.

The **QEMU native BEMF frontend** explicitly uses
`voltage=1.65+0.02*bemf`, mapping to a 3.3V 12-bit ADC via
`round(4095*voltage/3.3)`.
At **zero BEMF**, the model-based comparator midpoint code is 2048.
The SIM_ONLY board fixture now explicitly provides
`AM13E_BEMF_INITIAL_DAC_CODE=2048`, allowing the Guest's existing
`am13e_app_motor_bemf_reference_set()` to initialize CMPSS0 and
assert `reference_ready` legitimately. The earlier all-zero reference
was *not* an actual hardware measurement. This **must not** be reused
as a physical board-calibrated midpoint.

No bypass of the Motor Output Start, gate authorization, nFAULT,
BEMF reference readiness, OST/OC checks, or original fallback fault
handler occurred. Existing raw 2048 DAC codes for independent OC
comparators in this SIM_ONLY fixture are **uncalibrated**, not hardware
current trip points.

## 3. Direct20 raw-source A/B evidence

First positive external DShot follows 1500ms neutral. It remains
active for exactly 1500ms then is removed for 300ms. Both runs receive
all 3300 frames and have exactly 1500 1ms ROTOR samples inside the
positive-command interval.

| Source event/metric | Source-built control | Source-built 3ms/quarter |
|---|---:|---:|
| First physical CAP1 (ms since positive DShot) | 3.230328 | 3.230756 |
| First Guest TIMG12 (ms) | 17.789468 | 3.985920 |
| First changed physical PWM_PAIR (ms) | 17.833764 | 3.998240 |
| Powered-window min rotor RPM | -263.558 | **0.000** |
| Powered-window max rotor RPM | 319.461 | **885.831** |
| Powered-window ROTOR below -50 RPM | 549 | **0** |
| Powered-window PWM_PAIR events | 125 | **2745** |
| Powered-window CAP1_ACK events | 187 | **2745** |
| Powered-window TIMG12_ACK events | 124 | **2744** |
| Powered-window torque < -0.1 Nm samples | 667 | **311** |
| External DShot frames | 3300 | 3300 |

This directly distinguishes *no sustained/reversed rotor direction*
from *no negative torque*: 311 negative-torque samples remain in
candidate, so current/ripple, noise, power and stability are **NOT
fully qualified**.

## 4. Fail-closed next gates

- The original source-built CI compared first-50ms rotor motion.
  Follow-up commit `90141f424c0d7e3a9801df19be3435485443d389` changes
  the script to **require 1500/1500 positive rotor samples, no
  <-50rpm sample, >=12 physical PWM_PAIR/CAP1_ACK/TIMG12_ACK,
  and >=50rpm sustained real motion**. The newly named workflow
  run is [#40806638889](https://github.com/cctsao1008/escape32-qemu/actions/runs/40806638889).
- The separately tested pinned-ELF three-instruction Candidate
  previously passed all six scenarios in
  [#40791759457](https://github.com/cctsao1008/escape32-qemu/actions/runs/40791759457)
  (5 scenarios) and
  [#40791759454](https://github.com/cctsao1008/escape32-qemu/actions/runs/40791759454)
  (Direct20).
- The independent **source-built** five-profile scenario matrix is
  [#40806799665](https://github.com/cctsao1008/escape32-qemu/actions/runs/40806799665).
  Its outcome is separate from previous pinned-ELF tests.
- **Original Rel17.3 strict P0/P1 CI remains OPEN/FAIL** when the pinned
  immutable firmware is used. The new candidate is *not* the Original
  Guest and cannot inherit its identity or bypass scenario hashes.
- Any release candidate needs 3-phase BEMF comparator noise/glitch
  characterization, startup/restart and direction tests, motor/prop
  loading, genuine board reference sensing and OC/nFAULT safety
  validation. The quarter-window filter is intentionally
  **SIM_ONLY** until those safeguards are established.

**Verdict:** Source-level *causal reversal fix* demonstrated for
Direct20 in the current idealized ECX87 simulator, with real motor
events. Neither hardware maturity nor strict full-product P1
qualification is claimed.
