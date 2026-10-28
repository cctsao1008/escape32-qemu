# E62 — Neutral-Return Energy Ledger and Bounded AQ/DB Source Focus

**Status:** Model-level Source Evidence. Original ESCape32 Rel17.3 ELF pinned, no firmware, motor physics or P0/P1 acceptance changes. **Hardware OPEN, motor P1 strict OPEN.**

## Why the post-neutral response needs two independent observations

The existing native Source Events report a change from external FC DShot
raw 448 to 0 at **2800.025708ms**, with a short negative-electromagnetic-
torque transient and rapid modeled reduction in RPM. The 120ms native
\`SWITCH\` trace captures early carrier behavior, not switching late in
the 2800ms region. \`PWM_PAIR\` records powered-pair transitions, not every
16kHz carrier edge. Do not infer that zero DShot instantly equals
coasting, or that a negative model torque is proof of firmware active
braking.

## 1. Read-only ENERGY / INVARIANT audit: no QEMU rebuild

\`tools/native_source_energy_audit.py\` consumes an **original**
\`*.p0.events.log\` file, not the reduced GUI \`*.source-trace.json\`.
It requires consecutive source event sequences, virtual-time order, a
nonzero→zero DShot transition, a full focus window, complete cumulative
ENERGY source values and source INVARIANT tolerances. It refuses a
malformed/partial energy ledger, and reports the SHA256 of the actual log.
It never advances QEMU or reads/writes Guest/MMIO.

For the supplied local Oct 28 Smoke evidence:

\`\`\`bash
cd ~/github/escape32-qemu

python3 tools/native_source_energy_audit.py \
  --events artifacts/e62-native-20261028-193626.p0.events.log \
  --expected-sha256 f7ad07638b3af41d4316e8b80a86b8e2909cc4d3d4eaa56845ccf381001e500b \
  --window-ms 35 \
  --output artifacts/e62-neutral-20261028-193626-energy.json
\`\`\`

### Source-backed result: 2026-10-28 original log

- Exact DShot nonzero→zero source trigger: **2800.025708 ms**, seq **26994**.
- First and last post-neutral ENERGY samples: **2800.237408 to
  2834.237408 ms** (35 actual periodic source samples, **34ms**
  non-interpolated delta; do not claim an exact 35ms energy integral).
- ΔBus = **−0.049230638 J**, ΔDiode = **+0.008601044 J**,
  ΔCopper = **+0.100192776 J**, ΔBEMF = **−0.159571967 J**,
  ΔMagnetic = **−0.000181347 J**,
  ΔBackward-Euler Numerical = **+0.001728856 J**.
- Model electrical identity:
  \`ΔBus=ΔDiode+ΔCopper+ΔBEMF+ΔMagnetic+ΔEuler\`.
  The complete log's maximum serialized cumulative ledger residual
  is **2 nJ**. No measured electrical efficiency or power-supply
  regenerative behavior is inferred from the idealized bus model.
- Source \`PWM_PAIR\` after neutral:
  **2800.185016 ms**: pair 8, six-pad mask 24, gate word 15;
  **2801.268536 ms**: pair 2, mask 9, gate word 15.
- The original log has **zero \`SWITCH\` records in this late window**;
  this is a recording limitation, not proof of PWM OFF.

The negative BEMF source energy is consistent with mechanical-to-
electrical energy transfer inside this exact model. It does *not*
establish firmware-intentional active braking or verify hardware
energy conversion.

## 2. Opt-in bounded late six-pad switching source (new QEMU build)

When the energy ledger is insufficient to determine the causal switch
path, enable an **explicit, source-only focus window**:

\`-M am13e23019,...,esc-sim-switch-focus-window-ms=2795:2840\`

or use the unchanged native Original Guest/no-WFI test runner's
\`--switch-focus-window-ms 2795:2840\` forwarding option. The setting is
**OFF by default**, accepts only 1–50 ms windows within the first
180 seconds of QEMU virtual time, and is limited to **12,000 actual
AQ/DB six-pad state transitions**. An overflow emits
\`SWITCH_FOCUS_LIMIT\` and the audit fails closed.

The source observer emits \`SWITCH_FOCUS\` from the *existing* QEMU
virtual-clock PWM callback only when the actual mask or gate-valid
changes. Fields: \`a\` six-pad mask, \`b\` gate valid, \`c\` gate
word, \`d\` native motor integrated steps, \`e\` PWM zero
callbacks, \`f\` motor PWM notifications before event. Mask mapping:
bit 0 U_H, 1 U_L, 2 V_H, 3 V_L, 4 W_H, 5 W_L.

**Important:** this opt-in observer is an instrumentation change
requiring \`./build.sh\`; it is not a switch command generator and
cannot change the Guest, output mask, motor integrator, BEMF/OC
frontend, PWM/timer interrupts or P1 acceptance criteria. The
original \`SWITCH\` (first 120ms) and its strict P0 gate remain
completely separate.

Example after pulling latest main and rebuilding QEMU:

\`\`\`bash
cd ~/github/escape32-qemu
./build.sh

RUN_ID=$(date +%Y%m%d-%H%M%S)

python3 tools/native_source_live_runner.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-native-webgui-cfg.bin \
  --scenario scenarios/e62-native-p0-smoke.json \
  --switch-focus-window-ms 2795:2840 \
  --artifact artifacts/e62-focus-$RUN_ID.json \
  --port 8765 --hold
\`\`\`

The full source trace is \`artifacts/e62-focus-$RUN_ID.p0.events.log\`.
Run the same audit against it to report exact time-aligned focused
switch transitions, existing PWM_PAIR and ENERGY:

\`\`\`bash
python3 tools/native_source_energy_audit.py \
  --events artifacts/e62-focus-$RUN_ID.p0.events.log \
  --window-ms 35 \
  --output artifacts/e62-focus-$RUN_ID.energy.json
\`\`\`

For a valid observer result there must be actual
\`SWITCH_FOCUS\` in the requested window, no
\`SWITCH_FOCUS_LIMIT\`, and the Guest and motor original-source
sequence must remain unchanged apart from the new isolated records.

## 3. Differential reproducibility, then source-only observer check

CI: `.github/workflows/e62-neutral-source-focus-differential.yml`.

**2026-10-28 unsynchronized baseline finding:** The old OFF/ON CI
[#40689114983](https://github.com/cctsao1008/escape32-qemu/actions/runs/40689114983)
was not a valid attribution test: its first source DShot occurred at
656272ns OFF versus 68692ns ON, before the focus window. An independent
OFF/OFF CI
[#40691834765](https://github.com/cctsao1008/escape32-qemu/actions/runs/40691834765)
proved that the **observer-disabled baseline itself is not bit-exact**:
first DShot 260660ns and 56596ns, 28335/28336 original events through
2990ms, and unequal source ENERGY deltas. The default native runner
initially boots its Guest while the host performs QTest diagnostics
and then arms the independent FC timer at the **current QEMU virtual
time +100ns**. Host startup timing is therefore an uncontrolled input.
This finding does NOT prove an observer side effect or observer neutrality.

**Updated fail-closed order:**

1. Build QEMU and verify the *unchanged* pinned Original ELF and SIM_ONLY
   configuration.
2. Run **OFF-A** and **OFF-B** with the same smoke scenario. Require
   bit-exact original virtual timestamps, source order/payload and
   ENERGY delta through 2990ms; emit `e62-focus-off-repeatability.json`.
3. Only if OFF/OFF passes, run **ON** and require genuine bounded
   `SWITCH_FOCUS` transitions without budget overrun. Ignore only the
   new focus records when comparing original source events/energy,
   with no time shift, rounding, normalization tolerance or waived P0/P1.
4. Retain original logs and reports via CI artifact on all failures.

**2026-10-28 independent OFF/OFF evidence:** CI
[#40695903916](https://github.com/cctsao1008/escape32-qemu/actions/runs/40695903916)
completed both uninstrumented Guest runs and both original ENERGY audits.
The final comparison step itself failed on a Python import path
(`ModuleNotFoundError: tools`), but the preserved artifacts directly show
that OFF-A and OFF-B are *not* bit-exact:
- First DShot: **66032 ns** versus **45396 ns**.
- Original-source records through 2990 ms: **28335** versus **28336**.
- Original valid DShot feeds: **2380** versus **2381**.
- Neutral-window Bus energy delta: **-0.049230638 J** versus
  **-0.049217576 J**.
- After excluding only the first DShot event as an *investigative
  localization*, original records first diverge at approximately
  **2697.2374 ms**: ROTOR virtual timestamps **2697237408** versus
  **2697237656 ns** (248 ns apart), with different rotor/current and
  ENERGY payloads. This localization does **not** waive the strict
  first-event mismatch in the actual gate.

The dedicated comparator in
`tools/native_source_focus_differential.py` and its seven unit tests
make OFF/OFF equality a mandatory prerequisite and return
`FAIL_BASELINE_NONREPRODUCIBLE` without making an OFF/ON causal claim.
It preserves exact virtual timestamps, sequence/order, all six source
fields and signed source ENERGY deltas; no event dropping except isolated
focus instrumentation, no alignment and no tolerance.

The experimental runner separately supports QMP `-S` synchronized
startup and QEMU `icount record/replay`, but CI
[#40694606626](https://github.com/cctsao1008/escape32-qemu/actions/runs/40694606626)
showed that combining paused startup with recording blocked the first
QTest `readl 0x5ffeb000` for 20 seconds and produced a zero-byte
recording. This experimental path is **not yet validated** and is not
enabled in the current fail-closed Differential CI. The current workflow
uses the legacy free-running Original Guest for OFF/OFF controls, then
attempts ON only after the strict baseline passes. The experimental
runner's opt-in flags do not change production-like P0/P1 gate criteria.

**Acceptance boundary:** A/A replay equality is a prerequisite;
A/B equality can support source-only observation neutrality **within
that exact synchronized diagnostic replay**. Neither result qualifies
motor P1 stability, ESC hardware, thrust or thermal/current performance.

### Diagnostic preboot FC scheduling — deterministic-input experiment

A dedicated **default-off** QEMU machine property now prearms the exact
pinned `scenarios/e62-native-p0-smoke.json` 3000-frame input profile:

```
-M am13e23019,esc-sim=on,esc-sim-native-motor=on,esc-sim-differential-fc-smoke=on
```

This fixture runs during QEMU's initial machine reset, before the
original Guest executes. The independent PA26 DShot source is scheduled
on `QEMU_CLOCK_VIRTUAL` at reset epoch +100 ns, with the established
1 ms absolute frame deadlines. The machine-level diagnostic is rejected
unless `esc-sim` and `esc-sim-native-motor` are enabled and WWDT
BOOTRST is off. The four exact stage tuples are
`(1500,0,0,1), (1000,0,200,5), (300,200,200,1),
(200,0,0,1)`, meaning `(duration_ms, from_permille,
to_permille, update_ms)`.

`tools/native_preboot_fc_source.py` validates the input JSON against
those **exact** tuples and the original ELF SHA256, starts QEMU without
a QTest or QMP socket, and passively reads the complete chronological
QEMU stderr source. It checks every real `DSHOT` frame index
0..2999, leaves virtual time entirely to QEMU, and stops observing
only after the last frame. Comparison is restricted to original source
events **through 2990 ms**, safely before host teardown. The unchanged
`tools/native_source_energy_audit.py` runs against original traces
before the fail-closed OFF/OFF and subsequent OFF/ON source checks.

**Experiment separation:** This diagnostic does *not* use the
experimental `--differential-sync-start` / QMP `-S` or `icount`
record/replay path that previously blocked QTest. It eliminates
one known host scheduling variable, but deterministic startup inputs
alone do not establish whole-VM bit-exact execution. If OFF/OFF still
differs, preserve the precise first event and classification
`FAIL_BASELINE_NONREPRODUCIBLE`; do not shift virtual timestamps,
round numeric results, permit tolerance, or infer Observer side effects.
The input source is the *same physical PA26 waveform fixture* and the
Motor Plant, original ELF, native P0/P1 acceptance tests and safety
gates remain unchanged. Even an eventual A/B PASS is source-only
evidence for this specific replay, **not a Motor P1 PASS**.

## 4. Causal limits

Even with the focused switching available, combining DShot,
mask/gate, Rotor/Current/Torque, BEMF, ENERGY and CAP1/TIMG12 can
establish what the QEMU model did, not why the firmware author
intended it or what physical GaN/Si switches would do. Any claim
about hardware braking, discharge or thermal/current performance
requires measured physical evidence and independently defined
acceptance tests.
