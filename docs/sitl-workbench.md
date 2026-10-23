# E62 SITL Workbench — Phase 1 Offline Native Trace + Phase 2 Live Telemetry

The offline trace viewer and the new opt-in **localhost-only live
telemetry** share one read-only WebGUI. Neither path controls QEMU, reads
extra Guest state, alters native PWM, or qualifies real hardware.

## Phase 2: Live telemetry on an actual native sustained run

On an interactive Linux/WSL terminal, use the **existing** strict G13B3M
`tests/g13b2_native_drive_probe.py` command from the pinned
`.github/workflows/esc-sim-regression.yml`. Add:

```bash
--sitl-live-port 8765 --sitl-live-hold \
--sitl-trace-output artifacts/g13b3m-native-sitl-trace.json
```

Open **http://127.0.0.1:8765/** in the browser before or during the
run. The native probe prints `E62_SITL_LIVE_READ_ONLY_URL` with the exact
address. If 8765 is occupied, pick an available port or use
`--sitl-live-port 0` for an automatically assigned loopback port.
The optional `--sitl-live-hold` keeps the read-only dashboard accessible
after native completion until Ctrl-C. It requires an interactive TTY.
Without hold, the listener shuts down when the native probe finishes.
These options work **only** on the existing native sustained loop path.

The WebGUI automatically detects the local SSE endpoint when served from
localhost, while preserving the offline `Load trace JSON` mode.
Live data is sent via **read-only Server-Sent Events (SSE)**; there is no
remote login, no external scripts, and no command/firmware-control API.
The HTTP service binds to **127.0.0.1 only**, checks Host and Origin,
rejects POST, and serves only the viewer and /events.

The Guest/probe thread appends previously validated WFI snapshots to a
bounded **2048-frame in-memory ring**. Browser clients wait/read on
separate HTTP threads and cannot backpressure Guest RSP/QTest.
Reload/reconnect receives the current ring snapshot. Ring overflow,
subscriber gaps, and disconnects are explicitly labeled; the viewer
does **not** interpolate lost native evidence or treat missing samples
as continuous motion. The complete offline JSON can still preserve the
whole run, and is the preferred replay/provenance artifact.

**Caution:** "Live" refers to incremental publication as the native
QEMU run proceeds. Time is **ECAP virtual time**, not wall-clock
real-time performance. PWM is a **WFI-sampled carrier duty**, not
individual high-frequency switching edges. SIM_ONLY model RPM/BEMF
remain uncalibrated, not physical motor/board measurements.

The stream terminates with a native-probe result or exception indicator,
not the separate G13B3M strict gate. The WebGUI must display
`NOT EXECUTED` for that gate; it cannot declare a twelve-sector /
90 ms / rotor-continuity PASS from telemetry. Existing G13B3L and
G13B3M CI commands/gates are unchanged.

## Phase 1: Offline trace analysis
This is an **offline read-only viewer**, NOT a QEMU controller or a
production ESC configuration utility. It opens actual native WFI snapshots
from the optional `--sitl-trace-output` recorder. Its operation does not
change the original firmware, its ADC/BEMF stimulus, or any CI acceptance gate.

## Read actual firmware-backed CI trace

Download the **e62-qemu-integration** artifact from the associated GitHub
Actions run (even when G13B3M fails). It contains, on the fast native path,
`artifacts/g13b3m-native-sitl-trace.json`.

Open `web/sitl_trace_viewer.html` locally in a browser, use **Load trace
JSON**, and select the recorded file. The viewer has no external JavaScript
or network dependency. It shows six original MCPWM4 sampled high-tick
ratios, model BEMF three-phase voltages, model RPM, and accepted CAP1 /
TIMG12 source-native event markers. Hover a chart to see a WFI snapshot;
use Zoom, Pan, and event table selection to navigate virtual time.

## Local capture (example: after building the same pinned ELF/QEMU)

Take the *existing* strict G13B3M command from
`.github/workflows/esc-sim-regression.yml` and add:

```bash
--sitl-trace-output artifacts/g13b3m-native-sitl-trace.json
```

`--sitl-trace-output` is legal only for the native sustained-loop probe
and must not overwrite the main `--artifact`. Its output is produced
even if the probe later fails. The separate strict extended-run audit is
**unchanged** and can still fail due to rotor direction reversals.

## Data provenance and limits

- `metadata.elf_sha256`: SHA256 of the actual guest ELF.
- `t_ns`: QEMU ECAP1 TSCTR ticks relative to actual native gate-return
  sample. This is functional virtual time (5 ns/tick), **not measured
  silicon carrier timing** or host wall-clock time.
- `pwm_high_ticks[6]` and `pwm_duties[6]`: original firmware-owned
  MCPWM outputs sampled at Guest WFI, already observed by native probe.
  **NOT** a resolved PWM pin-edge waveform; inter-WFI transitions may
  have been missed. Never fabricate edges from averaged duty.
- `bemf_phase_v[3]`, `phase_currents_a[3]`, `motor_rpm`: existing
  simplified SIM_ONLY open-star virtual motor predictions, **not**
  a 47 V Queen Bee motor or an encoder / current probe measurement.
- `CAP1_ACCEPTED` and `TIMG12_SERVICED` events: original Guest-audited
  sectors, with actual ECAP timer ticks. Not Host-generated Guest IRQs.
- `native_result` contains *probe* evidence only; the recorder never
  runs or overrides `native_extended_run_gate.py`. Six/twelve sectors and
  90 ms alone cannot establish stable rotation.
- `capture_state=PARTIAL_EXCEPTION`: trace was preserved during failed
  native execution; do not treat the partial file as a PASS.

The recorder consumes existing Python objects at the same stopped WFI
checkpoint; it adds **zero** RSP commands, QTest commands, or Guest register
writes. No native Guest control is exposed by either phase. Phase 2 adds only a
localhost SSE reader; it does not add QEMU control or a WebSocket backend.
The existing hardware H0–H4 measurements remain OPEN_NOT_MEASURED.

## Verification

```bash
python3 tests/test_sitl_trace.py
python3 tests/test_sitl_live.py
python3 tests/test_sitl_viewer.py
```

These are host-only **format and safety checks**, not native firmware PASS.
The standard Host CI and full firmware-backed G13B3L/G13B3M runs remain
the source of regression and acceptance evidence.
