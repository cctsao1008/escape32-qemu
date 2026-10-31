# E62 Issue #5 — Audio-versus-Drive Source Timeline / Six-Step Order Audit

**2026-10-31. Original ESCape32 Rel17.3 firmware is immutable. SIM_ONLY QEMU observer and host-side read-only auditor only; Original P1 unchanged. Issue #5 still OPEN.**

## Why this test exists

Rel17 `src/main.c` performs `playmusic(cfg.music, cfg.volume)` on normal power-on and uses `playmusic("GC" or "G_GC")` following arming. `src/util.c::playmusic()` calls the shared MOTOR MCPWM audio backend, and AM13E `motor_audio.c` alternates U/W audio compare values, with a tone-dependent PWM period. `motor_safety.c::am13e_app_motor_audio_begin/end()` requires exclusive Motor/Audio ownership and restores the idle DRIVE image upon audio exit.

These source facts establish **possible rotor vibration from music**, not that the recorded repeated forward/reverse behavior under a long sustained DShot demand originates from music.

Firmware source (unchanged):
- [ESCape32 main.c](https://github.com/cctsao1008/ESCape32/blob/am13e-port-v2/src/main.c)
- [ESCape32 util.c](https://github.com/cctsao1008/ESCape32/blob/am13e-port-v2/src/util.c)
- [ESCape32 motor_audio.c](https://github.com/cctsao1008/ESCape32/blob/am13e-port-v2/mcu/AM13E/hal/motor_audio.c)
- [ESCape32 motor_safety.c](https://github.com/cctsao1008/ESCape32/blob/am13e-port-v2/mcu/AM13E/hal/motor_safety.c)

## Prior 47 V raw evidence (no new instrumentation yet)

The four original source artifact ZIPs from [run #41109233164](https://github.com/cctsao1008/escape32-qemu/actions/runs/41109233164) each show 5,100 actual source DShot frames for neutral 1,500ms, 20% demand 1,500ms, neutral 300ms, 20% demand 1,500ms, neutral 300ms. Rotor RPM was zero in the initial neutral stage, with large positive and negative rotor RPM in both demand stages. These files were emitted *before* the newly added clock-period instrumentation and thus **do not prove exact audio ownership times**.

Independent read-only decoded `PWM_PAIR` stage transitions:

| 47 V model | First demand `PWM_PAIR` events | Second demand `PWM_PAIR` events | Non-adjacent transitions in 6-step order |
|---|---:|---:|---:|
| KV210 / no prop control | 211 | 211 | 0 / 0 |
| KV210 / APC J1 | 211 | 212 | 0 / 0 |
| KV210 / APC J2 | 149 | 148 | 0 / 0 |
| KV210 / APC J5 | 93 | 97 | 0 / 0 |

Observed repeat sequence: `8 -> 2 -> 3 -> 6 -> 4 -> 7 -> 8`, where `pair=1+3*high_phase+low_phase` is QEMU's encoded positive/negative phase-pair identifier. Native pad masks in sequence: `24, 9, 33, 36, 6, 18`, with no same-leg overlap in these complete selected pairs. The original Rel17 six-step plan is in `src/main.c` and AM13E `motor_phase_plan.c`.

**Important:** Correct *digital* pair progression does not validate physical U/V/W wiring, current polarity, rotor-angle zero, BEMF mux/neutral reference, capture IRQ timing, or a torque-positive actual electromagnetic phase relationship. Strict P1 in [#41110182593](https://github.com/cctsao1008/escape32-qemu/actions/runs/41110182593) still failed all four profiles on `STARTUP_SIGNIFICANT_DIRECTION_REVERSAL`.

## Newly committed opt-in QEMU hardware observers

1. `PWM_TBCTL` source event on actual Guest MCPWM `TBCTL` register *change*: six fields = old TBCTL, new TBCTL, active period, model clock Hz, running flag, zero-event count.
2. `PWM_AUDIO_PERIOD` source event on actual Guest ACTIVE carrier period change **while TBCTL divider code is 5 (/32)**: six fields = prior period, new period, TBCTL, clock Hz, running flag, zero-event count.
3. `tools/e62_audio_motor_timeline.py` overlays these events against *source-owned DShot frame timestamps*, actual source `PWM_PAIR` masks, and source `ROTOR` samples. Reports an unqualified `clock_div32_is_music_candidate_not_proof`; explicitly does **not** assert it has read the firmware-private `audio_owner`.
4. P0 parser now admits these **two exact native QEMU source event types** while preserving the existing continuous sequence/time checks, unknown-event rejection, all strict P0/P1 physics/control acceptance gates, and no-waiver tests. **No artificial PWM, comparator, BEMF or Guest memory write.**
5. Both existing 24V and 47V Original Guest CI workflows run the same *diagnostic-only* offline auditor and retain its JSON alongside strict P1 outcome; P1 FAIL must still fail the job.

**Limits:** A late /32 candidate during a positive demand requires investigation, not automatic proof of music ownership. No /32 event during a demand is **not** proof that the software `audio_owner` flag has been released; the analyzer labels it `NOT_EXCLUSION`. Music may impose initial-condition changes before first demand even when no later sound exists. First demand itself fails sign stability in 24/47 V models, so do not attribute these broad failures solely to 300ms coast or to music by speculation.

## Results / release gate

- Host parser/auditor regression: [new model-source study CI](https://github.com/cctsao1008/escape32-qemu/actions/workflows/e62-apc24x12e-47v-sim-only.yml), actual run result must be consulted before declaring PASS.
- Original 24 V control CI: [24V baseline workflow](https://github.com/cctsao1008/escape32-qemu/actions/workflows/e62-24v-baseline-sim-only.yml), independently source-built.
- The next root-cause decision requires source-verified audio/drive time separation, six-pad phase-mask versus rotor torque at the same virtual timestamps, and BEMF comparator/ECAP1/TIMG12 timing; no software-only retroactive P1 acceptance.
- No ESCape32 Firmware edits for QEMU compatibility. A firmware change may only be considered if a separately proven genuine bug is documented and reviewed.
