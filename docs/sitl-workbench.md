# E62 SITL Workbench — Phase 1 Offline Native Trace

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
writes. No backend/WebSocket or live QEMU control is included in Phase 1.
The existing hardware H0–H4 measurements remain OPEN_NOT_MEASURED.

## Verification

```bash
python3 tests/test_sitl_trace.py
python3 tests/test_sitl_viewer.py
```

These are host-only **format and safety checks**, not native firmware PASS.
The standard Host CI and full firmware-backed G13B3L/G13B3M runs remain
the source of regression and acceptance evidence.
