# E62 Python ESC-SIM Interactive Console

This is **not** the original ESCape32 Guest UART or the ESP32 WiFi-Link
stack. It copies the familiar ESCape32 command vocabulary
(`help`, `info`, `show`, `get`, `set`, `throt`) for the
**simulator external flight-controller** and allows viewing read-only
original Guest and QEMU virtual hardware diagnostics.

The original firmware ELF remains immutable:
`05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
No -S, GDB, Guest WFI stepping, Guest peripheral configuration writes,
Guest SRAM writes, nor fake BEMF inputs. The native QEMU motor is
clocked by the real Guest MCPWM4 six-pad switching source.

## Start

```sh
cd ~/github/escape32-qemu
git pull --ff-only
./build.sh
python3 tools/e62_sim_cli.py
```

The CLI checks the original ELF hash, and if needed runs
`sim_motor_cfg.py --sim-only-opt-in` for the **dedicated**
original-ELF `telem_poles` pre-boot flash CFG. Neither Guest FW nor
on-silicon settings are modified.

Default scenario: `scenarios/e62-native-console-10s.json` (1.5 seconds
neutral + 8.5 seconds neutral = 10 seconds of QEMU virtual-time, every
1ms an external physical PA26 DShot600 frame). The user may issue a
live `throt` override inside this period. QEMU executes changes at
the next **virtual 1kHz DShot frame** and writes immutable
source `THROT_SET` and `DSHOT` events with exact virtual timestamps.
Host wall-time command scheduling is interactive/non-deterministic;
for strict reproducibility use `load` with a versioned JSON timeline.

## Commands

```text
e62-sim> help
e62-sim> info
e62-sim> show scenario
e62-sim> load scenarios/e62-native-p0-gentle.json
e62-sim> run
e62-sim> status
e62-sim> show guest
e62-sim> get guest.valid_frame_feeds
e62-sim> get motor.rpm
e62-sim> get safety.ost_latch
e62-sim> show cfg
e62-sim> get cfg.telem_poles
e62-sim> history 10
e62-sim> watch 1
e62-sim> throt 0
e62-sim> throt 15.5
e62-sim> throt auto
e62-sim> results
e62-sim> stop
e62-sim> quit
```

- `load <file.json>`: validate schema, original Guest SHA, timing,
  stages, input limits and load pre-run. Cannot replace a running
  scenario; use `stop` first.
- `run`: start autonomous Guest QEMU and QTest observability channel,
  stage the **external** FC DShot profile, return prompt immediately.
- `status`: source frame counter, observed motor RPM, PWM output
  mask, Guest CRC reception, OST trip flags.
- `show [scenario|sim|guest|all]`: stage information, live read-only
  Guest symbols and emulator diagnostics (not all firmware CFG).
- `get domain.field`: read one known value, e.g. `guest.throt`,
  `motor.rpm`, `source_dshot.live_changes`. No arbitrary
  MMIO address reads or writes.
- `throt <percent>`: 0 to 100%, **0.1%** resolution. Sets the
  external FC override only in a currently running simulation.
  It does NOT invoke the original firmware's `throt [-2000..2000]`
  command. The Guest still receives the value through real PA26/
  TIMG4/DMA DShot and controls its own PWM as usual.
- `throt auto`: release live override, resume source-clocked JSON
  stage value at the next frame. `throt 0` sends real zero-DShot
  repeatedly until the scheduled scenario ends.
- `watch [wall_seconds]`: human-friendly status polling only,
  never advances Guest or source clock; Ctrl+C stops the monitor.
- `fault load scenarios/e62-native-p1-nfault.json`, `fault show`,
  `fault clear`: only pre-run external physical PA22 fixture.
- `set monitor_interval <wall_seconds>`: UI-only setting.
  `set` Guest firmware/CFG is deliberately unsupported.
- `results`: after DONE, save Guest snapshots and complete
  native source events as JSON and `*.p0.events.log`.
  A console observation file is **not** a P0/P1 strict PASS.
- `stop`: request external FC zero throttle and attempt to observe
  ten further virtual frames if active, then terminate the QEMU
  *simulator*. It always preserves `STOPPED_BY_OPERATOR_NOT_A_TEST_PASS`
  JSON plus a complete `*.p0.events.log` after QEMU exits, including
  the number of actual subsequent FC frames (which may be fewer than ten
  if communication/progress fails). These are **aborted-run evidence**,
  not a qualified P0/P1 result or proof of actual motor safe-off.
  `results` can inspect the interrupted run's status and frame count.

**Distinguish:**
- **ORIGINAL GUEST CLI**: original `help/info/show/get/set/save/reset/
  play/throt/beep` commands on actual ESC serial line; not emulated
  or hijacked by this Python console.
- **ESC-SIM Console**: external FC scenario and live PA26 source
  plus read-only original Guest/QEMU observability.
- **P0/P1 acceptance**: original verified JSON, full source clocks,
  safety and physics independent gates. Manual override invalidates
  the original deterministic DShot JSON conformance check; do not
  call it `PASS_NATIVE_P0_STRICT` automatically.

## Safety and scope

Only uncalibrated 24V ECX87-KV147 **SIM_ONLY** plant is represented.
No hardware, GaN, 12S, current-sense amplifier, propeller, temperature,
flight-control certification or real ESC CLI settings are qualified.
`throt` may start a **virtual** motor. The live override is recorded
as a simulator-origin external command, not firmware-owned speed
control. Never connect this tool to hardware without an independent
review and safety interlock.

The verified **SIM_ONLY preboot** CFG byte at offset 57 may be inspected
via `get cfg.telem_poles` or `show cfg`. This is not a firmware UART
parameter dump: it only reports the dedicated 336-byte preboot image.
`history [n]` displays source-owned DShot and THROT_SET virtual-clock
events from the active/completed QEMU stderr log.

## Read-only Rel17 arming diagnostics

The Original Guest `src/main.c` ARM loop invokes
`am13e_app_motor_arming_window_start()`, waits **250ms of uninterrupted
zero throttle**, and restarts this window whenever `throt != 0`.
Manual `throt 50` before completion can therefore leave Guest throttle
accepted via CRC while `step=0` and motor RPM=0. This is NOT evidence
of a broken DShot receiver or a motor-physics model. The CLI now
passively reads the original ELF's uniquely resolved
`window_active` (uint8), `window_started_at` (uint32) and
`tick` (16kHz), via read-only QTest Guest SRAM access.

```text
e62-sim> status
e62-sim> show guest
e62-sim> get arming.window_active
e62-sim> get arming.window_elapsed_ms
e62-sim> throt 0
```

The observation is **non-atomic** because Guest is never halted. If
ELF symbols are missing or ambiguous it reports UNKNOWN rather than
guessing. `window_active=false` is **not an armed confirmation**:
Guest may not yet have entered the arming loop or may already have
exited it. The FC source still transmits DShot independently of
Guest arming. A warning after a positive interactive throttle when
`window_active=true` is informational only, not a host readiness
interlock. To ensure the clean reference startup scenario, use the
versioned 1.5-second neutral-then-ramp JSON scenario.
