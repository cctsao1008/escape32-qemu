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

## What the viewer does *not* prove

- Source-event BEMF is an **ADC comparator input code**, not volts.
- Source-event PWM is a **sparse instantaneous six-pad mask**, not the real PWM carrier or an averaged duty. Stale masks are blank, not interpolated.
- DShot chart is blank after 2 ms without a source command. It does not pretend the last throttle was re-sent.
- Rotor, current and torque are an **uncalibrated SIM_ONLY motor model**, not physical ESC/motor measurements.
- The viewer does **not** execute or waive the P1 motor reversal/stability gate. Original direct20/steps P1 dynamics FAIL remain FAIL.
- The WebGUI uses localhost-only, read-only SSE, never a firmware-command interface.

For design, exact data contracts, diagnostics, CI and source provenance, see [No-WFI Native Source WebGUI](../docs/current/e62-native-source-webgui.md) and [SITL Workbench](../docs/sitl-workbench.md).
