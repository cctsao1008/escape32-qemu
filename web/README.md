# E62 SITL Workbench — No-WFI / WFI Viewer

The single-file [SITL Workbench](sitl_trace_viewer.html) supports two **distinct read-only** data sources:

| Mode | Source format | What is plotted |
|---|---|---|
| Original WFI Trace | `e62.sitl.native-wfi.v1` | WFI-sampled six PWM carrier **duties**, RPM, model-volts BEMF, phase currents and Guest sector events |
| Original No-WFI Native Source | `e62.sitl.native-source.v1` | Source-owned DShot, sparse actual six-pad PWM **mask**, simulated signed RPM, currents, torque, BEMF **ADC codes**, CAP1/TIMG12 |

## Throttle Profile Editor (offline native DShot600 scenario JSON)

Expand **Throttle Profile Editor** near the top of the existing single-file
`sitl_trace_viewer.html`. This works under `file://` without a Python
web server, without running QEMU, and while the read-only trace viewer
remains independent.

1. Select a built-in `Smoke`, `Gentle`, `Direct20`, or `Steps`
   preset; these are exact copies of `scenarios/e62-native-p0-*.json`.
   Alternatively, use **Import native Scenario JSON** for a file you
   already have, including other valid `e62.native.dshot.v1` tests.
2. Edit scenario name or any `Hold`/`Ramp` stage, remove stages, or
   add a stage before the terminal neutral stage.
3. Review the **commanded throttle (%) versus virtual time (s)** preview.
   The display shows bounded discrete command steps, **not actual motor
   speed or physical DShot pin edges**. For very dense ramps the preview
   decimates samples for drawing; the exported JSON retains the exact
   original timing and update interval.
4. **Export Scenario JSON** becomes enabled only when the current draft
   passes the native scenario schema contract. Save the downloaded JSON
   and pass its path to the existing native runner, e.g.
   `--scenario scenarios/my-throttle-profile.json`. Exporting does not
   start QEMU or alter an existing Guest.

**Validation constraints:** Original Rel17.3 ELF SHA256 pinned;
`protocol=DSHOT600`; 1,000,000 ns between transmitted frames;
`guest_ready_gating=false`; 2–16 stages, each lasting 10–120,000 ms;
0–1,000 integer permille (100=10%); first/last stages neutral;
exactly divisible ramp update and integer-permille increments; ramp
start must equal previous stage end; max total 180,000 ms. Invalid
fields disable export. Scenario JSON imports are limited to 256 KiB.

These checks mirror `tools/native_dshot_scenario.py`; CI checks each
built-in against the repository and validates exported JSON with the
real Python compiler. **Throttle Profiles are files, not interactive
ESC commands.** This editor does not alter the existing No-WFI
QEMU, firmware, motor plant, or P0/P1 acceptance criteria.

## Open an existing offline trace

1. Obtain a real `*.source-trace.json` artifact (for example from [No-WFI QEMU source CI](https://github.com/cctsao1008/escape32-qemu/actions/runs/40669622679)).
2. Open `web/sitl_trace_viewer.html` locally in a browser.
3. Use **Load trace JSON** and select the file.

This also works for the original `e62.sitl.native-wfi.v1` files. No Python server is necessary to review an existing file.

## Watch a No-WFI QEMU run live

On Linux/WSL, build the repo's source QEMU, prepare the original-GUEST-derived SIM_ONLY configuration and start the **read-only wrapper**:

```bash
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
```

Open **http://127.0.0.1:8765/** on the same computer.
`--hold` needs an interactive terminal and retains the dashboard after the probe finishes. Each run must use a **new** `--artifact` path; the wrapper refuses existing files rather than displaying stale evidence.

When selecting an offline file in a live page, the browser **disconnects SSE** to prevent mixing two sources. Reload the page to reconnect. Gaps/truncated history remain explicitly marked.


## No-WFI source observability and neutral-return focus

No-WFI Live now shows a real SSE state: connected, probe finished or
disconnected. The separate WFI-duty instructions only appear for WFI.

The No-WFI **BEMF Y-axis** selector offers centered about code 2048
(default), autoscale to visible source samples, or full 0–4095 ADC
codes. These are **ADC codes, not voltage measurements**.

The six-pad **SWITCH mask coverage** shows the first/last fresh source
samples and explains when the initial **120 ms after first-switching**
logging budget is exhausted. Blank later source masks do not prove
PWM OFF or that a particular PWM carrier edge was absent.

**LIVE RING HISTORY LIMIT** means older samples were evicted from
the browser-side 2048-frame view; it does not mean QEMU Source Events
were lost. **SSE STREAM GAP** means packets unavailable to that
browser connection; neither is interpolated.

**Inspect DShot → 0 (+35 ms)** derives the neutral return from an actual
external-FC DShot Source Event; it focuses all source plots on the next
35 ms QEMU virtual-time interval, showing observed RPM, torque,
sampled current peak and CAP1/TIMG12 events. A separate
**Full available trace** button resets the viewport. This does NOT
establish that the motor was actively braked or coasted.

On your WSL, inspect an already saved Smoke Source Trace without
rerunning QEMU:

    cd ~/github/escape32-qemu
    python3 tools/native_source_neutral_diagnostics.py \
      --trace artifacts/e62-native-20261028-193626.source-trace.json \
      --window-ms 35 \
      --output artifacts/e62-neutral-20261028-193626-observation.json

This CLI is source-only and does not send commands to the Guest,
QEMU or the Motor Plant.


## Optional bounded late PWM switching focus (requires rebuild)

New QEMU source-only observability emits \`SWITCH_FOCUS\` at real
AQ/DB six-pad mask/gate transitions during a **1–50 ms** explicitly
specified virtual-time window. Default is **OFF**. A separate
**Opt-in 6-pad AQ/DB SWITCH_FOCUS events** WebGUI chart displays
original source transition points, not a reconstructed carrier
waveform. Source snapshots include \`pwm_mask_source_kind\` so
early normal \`SWITCH\` and optional late \`SWITCH_FOCUS\` are
not confused.

After \`git pull --ff-only\`, run \`./build.sh\` to rebuild the
new QEMU observer. Reuse your unchanged Original ELF and SIM_ONLY CFG:

\`\`\`bash
RUN_ID=$(date +%Y%m%d-%H%M%S)

python3 tools/native_source_live_runner.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-native-webgui-cfg.bin \
  --scenario scenarios/e62-native-p0-smoke.json \
  --switch-focus-window-ms 2795:2840 \
  --artifact artifacts/e62-focus-$RUN_ID.json \
  --port 8765 --hold

python3 tools/native_source_energy_audit.py \
  --events artifacts/e62-focus-$RUN_ID.p0.events.log \
  --window-ms 35 \
  --output artifacts/e62-focus-$RUN_ID.energy.json
\`\`\`

This observer is **not** an ESC command or a new motor model. It
records only real source callbacks; its 12,000-transition budget
fails closed on overflow. Source data will not certify physical
braking, analog current, or motor P1 acceptance. See
[Energy Ledger and Bounded AQ/DB Focus](../docs/current/e62-neutral-energy-and-focused-switch-observation.md)
for original Oct 28 model measurements, limits and the
Off/On nonintervention regression.


## What the viewer does *not* prove

- Source-event BEMF is an **ADC comparator input code**, not volts.
- Source-event PWM is a **sparse instantaneous six-pad mask**, not the real PWM carrier or an averaged duty. Stale masks are blank, not interpolated.
- DShot chart is blank after 2 ms without a source command. It does not pretend the last throttle was re-sent.
- Rotor, current and torque are an **uncalibrated SIM_ONLY motor model**, not physical ESC/motor measurements.
- The viewer does **not** execute or waive the P1 motor reversal/stability gate. Original direct20/steps P1 dynamics FAIL remain FAIL.
- The WebGUI uses localhost-only, read-only SSE, never a firmware-command interface.

For design, exact data contracts, diagnostics, CI and source provenance, see [No-WFI Native Source WebGUI](../docs/current/e62-native-source-webgui.md) and [SITL Workbench](../docs/sitl-workbench.md).
