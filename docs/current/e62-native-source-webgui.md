# E62 No-WFI Native Source WebGUI — Read-only Live and Offline (2026-10-28)

## Decision and source boundaries

The existing single-file [SITL Workbench](../../web/sitl_trace_viewer.html)
supports **two explicitly distinct source formats**:

| Mode | Source | Display contract |
|---|---|---|
| Existing WFI | \`e62.sitl.native-wfi.v1\` original WFI snapshots | Sampled PWM *duty*, three-phase BEMF volts from previous model, RPM, Guest WFI state |
| New No-WFI | \`e62.sitl.native-source.v1\` actual \`E62_P0_EVENT\` in QEMU stderr | Physical-format DShot, actual six-pad SWITCH *mask* when fresh, original Guest CAP1/TIMG12 events; native modeled RPM, torque, currents, three **BEMF ADC codes** |

**No-WFI WebGUI is observation-only, not a second emulator or an
independent process for simulated FC/motor.** The actual original ELF, QEMU
native motor and PA26 DShot generator stay identical. Python runs the
existing original No-WFI probe and tails its preexisting QEMU stderr log.
It never opens a Guest GDB/QTest socket or modifies any MMIO, motor
inertia, BEMF, PWM, IRQ, source clock or acceptance policy.

The GUI **must not claim** the No-WFI six-pad mask is a 16kHz carrier
waveform: it only draws snapshots of actual source SWITCh event mask
when its timestamp is recent (<= 2ms). BEMF values are 12-bit ADC
codes, NOT volts; the old WFI model-volts chart remains unchanged.
Samples are source-owned QEMU virtual timestamps, not wall time or
hardware measurements.

## Live example from existing source-built Guest QEMU

Run from repo root on Linux or WSL; the baseline is the pinned original
Rel17.3 ELF (SHA-256:
\`05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0\`).

\`\`\`bash
./build.sh
mkdir -p artifacts
python3 tools/sim_motor_cfg.py --sim-only-opt-in \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --motor-profile ecx87-kv147 \
  --output artifacts/e62-g13b3-native-webgui-cfg.bin

python3 tools/native_source_live_runner.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-native-webgui-cfg.bin \
  --scenario scenarios/e62-native-p0-smoke.json \
  --artifact artifacts/e62-native-webgui-smoke.json \
  --port 8765 --hold
\`\`\`

Open **http://127.0.0.1:8765/** during the run. The runner prints
\`E62_NATIVE_NO_WFI_SOURCE_LIVE_URL\`. \`--hold\` requires a real terminal;
the dashboard remains open for investigation after the Guest exits
until Ctrl-C. Without \`--hold\`, the server closes when the probe
and source conversion finish. Use \`--port 0\` for a temporary loopback
port, and read its printed URL.

To view another behavior use a pinned JSON scenario such as:
\`scenarios/e62-native-p0-direct20.json\` or
\`scenarios/e62-native-p0-steps.json\`. Use a **new --artifact path each
time**; the wrapper rejects previously existing artifacts rather than
silently displaying stale source traces.

### Offline trace (works without running QEMU)

The live runner automatically produces:

- \`artifacts/e62-native-webgui-smoke.json\` — original probe verdict
- \`artifacts/e62-native-webgui-smoke.qemu.log\` — complete QEMU stderr
- \`artifacts/e62-native-webgui-smoke.p0.events.log\` — exact source events
- \`artifacts/e62-native-webgui-smoke.source-trace.json\` — complete
  offline read-only No-WFI GUI data

Open \`web/sitl_trace_viewer.html\` in a browser and use **Load trace
JSON** to load \`*.source-trace.json\`. The old WFI trace
(\`e62.sitl.native-wfi.v1\`) still loads in the same page.

To convert an already archived real native P0/P1 event log to offline
GUI JSON (no simulated plant run):

\`\`\`bash
python3 tools/native_source_trace.py \
  --events artifacts/e62-native-webgui-smoke.p0.events.log \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --output artifacts/e62-native-source-offline.json
\`\`\`

The converter rejects malformed or missing source sequences,
backward virtual time, missing real ROTOR/BEMF source pairs, unknown
event names, invalid original Guest ELF identity and exhaustion of
explicit record budgets. It does **not** construct fake or interpolated
BEMF, six-pad PWM, guest ISR or commutation transitions.

### GUI data gaps and sampling limits

- ROTOR + BEMF_FRONTEND from the same QEMU callback creates one
  model sample, normally every 1ms virtual. This is **not** 1ms wall
  time and not a 1µs waveform capture.
- The sparse source SWITCH record is only emitted for a **bounded
  startup window**. A mask older than 2ms is marked unavailable
  (blank chart) instead of being falsely extended as current PWM.
- Full native source counters (CAP1, TIMG12, actual WWDT feed) are
  from event log callbacks. A Guest CAP1 MMIO read is not an
  observed firmware-internal accept/reject return.
- The Live SSE server keeps a 2048-frame ring. Slow browser,
  disconnect and reconnect may show **DATA GAP / RING TRUNCATED**;
  use complete offline JSON for retrospective analysis. Never
  interpolate unobserved source.
- Live telemetry never calls or overrides the separate strict P0/P1
  motor/physics gate. The GUI labels Motor Strict P1 as
  **NOT EXECUTED**. direct20 and steps strict motor-dynamics FAIL
  remain unchanged.
- localhost-only SSE, no POST, no command API, no external JS/CDN.

## Verification

Read-only host tests:

\`\`\`bash
python3 tests/test_native_source_trace.py
python3 tests/test_native_source_live_runner.py
python3 tests/test_sitl_live.py
python3 tests/test_sitl_viewer.py
\`\`\`

CI: \`.github/workflows/e62-native-source-webgui.yml\`.

Actual pinned source-built QEMU + no-WFI wrapper smoke:
\`.github/workflows/e62-native-source-webgui-integration.yml\`.

These results are a **telemetry integration check** only. They are not
AM13E hardware, propeller, analog timing, or motor stability signoff.
