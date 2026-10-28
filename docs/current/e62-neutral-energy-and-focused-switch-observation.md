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

## 3. Differential no-intervention validation

CI: \`.github/workflows/e62-neutral-source-focus-differential.yml\`.
Using **the same pinned Guest and same Smoke scenario**, build QEMU
once and run **focus OFF** and **focus ON**. Ignore only the
\`SWITCH_FOCUS\` instrumentation records when comparing original
native sources up to virtual 2990ms. Compare all original timestamp,
event kind and six integer fields. Fail if any discrepancy, missing
focused switching, budget overflow or changed energy deltas.

The P0 audit recognizes the new source event *kind* but does NOT
count it as a normal \`SWITCH\` record or waive any original strict
gate. Focus observer diagnostics and P1 motor stability are
distinct tasks.

## 4. Causal limits

Even with the focused switching available, combining DShot,
mask/gate, Rotor/Current/Torque, BEMF, ENERGY and CAP1/TIMG12 can
establish what the QEMU model did, not why the firmware author
intended it or what physical GaN/Si switches would do. Any claim
about hardware braking, discharge or thermal/current performance
requires measured physical evidence and independently defined
acceptance tests.
