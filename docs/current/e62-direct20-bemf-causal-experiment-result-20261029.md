# E62 Direct20 sensorless BEMF startup: controlled QEMU causal result (2026-10-29)

**Status: Direct20 reversal resolved within the specified SIM_ONLY experimental
1.5-second positive-command run. NOT original-Guest P1 qualification,
NOT production or physical power-stage sign-off.**

## Same electrical and model inputs

- Source run: [#40734344571](https://github.com/cctsao1008/escape32-qemu/actions/runs/40734344571) **SUCCESS**.
- Artifact: `e62-direct20-original-vs-exact-3-instruction-candidate-NOT-P1`
  (artifact ID `12836758817`), includes original/candidate ELFs,
  original event logs, JSON evidence, exact byte diff.
- Real Original Rel17.3 control ELF SHA256
  `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
- Candidate SHA256
  `0975dd2169b308e1b4a3d131078f744ab6c0f6efa6acc65c7953d2a5f9ecfcd5`.
- Candidate differs from pinned ORIGINAL in only three Thumb-2
  instructions (nine ELF bytes), all verified against exact original
  opcodes/segment locations:
  - `src/main.c:1027`, VA `0x69e4`: startup `ival=10000` -> `3000`.
  - `src/main.c:1146`, VA `0x6a6a`: startup `ival=10000` -> `3000`.
  - `src/main.c:486`, VA `0x64ae`: `cmp.w r4,r2,asr #1` ->
    `cmp.w r4,r2,asr #2` (early acceptance `ival/2` -> `ival/4`).
- Timeout/desync reset at VA `0x6488` retains original 10ms; no PWM
  step map change, comparator wiring/phase map change, OC/Trip bypass,
  modified Host physical plant, Guest memory writes, or P1 rule waiver.
- Identical corrected ECX87 KV147 Motor Plant, identical config SHA
  `ab144c4b281ec53feb399b45c758b1de72b2c16f252e6ff64980f263b3a51702`,
  identical QEMU binary SHA
  `c4455609de065f5887330dd10eb62ae40dc50e8ebd664de83223c08364fc0e52`.
- Exactly **3,300** physical external PA26 DShot frames:
  1,500ms neutral, 1,500ms Direct20, 300ms neutral.

## Cause and independently visible evidence

The selected fourth six-step vector switched on at **+6.580524ms**
(relative to first positive DShot) in the original-3ms startup
counterfactual, followed by a genuine CAP1 at **+7.032080ms**:
**451.556us** after commutation.

The prior accepted crossing set a `T12_LOAD` of 57,399 ticks at
100MHz (573.99us), consistent with `ival/2` early rejection;
no `T12_LOAD` followed that CAP1 and the next effective PWM step
was delayed until **+18.749184ms**. The held fourth vector
produced negative torque and positive->reverse rotor reversal.

Keeping identical startup 3ms but changing early rejection from
`ival/2` to `ival/4` **accepts the next source CAP1 and continues
six-step commutation**. This preserves physical CAP1->TIMG12->PWM
causality, rather than artificially scheduling commutation from Host.

### Full powered-stage results, same 1.5s window

| Source metric | Original 10ms / half | 3ms / quarter |
|---|---:|---:|
| First physical CAP1 after positive DShot | 3.0283 ms | 3.0283 ms |
| First Guest TIMG12 | 16.7711 ms | 3.7711 ms |
| First changed PWM_PAIR | 16.8321 ms | 3.8300 ms |
| Fifth PWM_PAIR | 56.422 ms | 7.581 ms |
| First 50ms minimum RPM | -279.260 | 0.000 |
| First 50ms maximum RPM | 354.643 | 819.821 |
| Positive 1,500ms observed RPM min/max | -279.260 / 354.643 | **0.000 / 834.989** |
| Powered-window rotor samples below -50rpm | 558 | **0** |
| Powered-window torque negative (>0.1Nm magnitude) samples | 667 | 359 |
| Powered-window physical PWM_PAIR changes | 132 | 2,594 |
| Total source CAP1 events | 135 | 2,608 |
| DShot frames received | 3,300 | 3,300 |

These values were independently re-counted from the unmodified
per-run `.qemu.log` artifact and JSON. The candidate is
**NOT** proven torque-ripple-free: there are 359 measured negative
torque samples during positive command. They **did not** drive
negative mechanical RPM during this exact experimental run.

The previously tested 3ms / half candidate
[run #40728582673](https://github.com/cctsao1008/escape32-qemu/actions/runs/40728582673)
still reversed at **+12.235ms**, demonstrating that just
shortening the initial interval is insufficient.

## Source-level candidate, always Motor Output enabled for E62 motor tests

The corresponding guarded **source** test variant lives in
[cctsao1008/ESCape32 / e62-sim-early-bemf-startup-20261028](https://github.com/cctsao1008/ESCape32/tree/e62-sim-early-bemf-startup-20261028).

- Explicit `AM13E_SIM_ONLY_EXPERIMENTAL_EARLY_BEMF=1` selects
  initial 3000us and early capture `ival/4`; macro absent preserves
  Original Rel17 algorithm, including 10ms / half threshold.
- Independent E62 compile guard `AM13E_E62_REQUIRE_MOTOR_OUTPUT=1`
  **fails the build** unless
  `AM13E_MOTOR_OUTPUT_CONFIGURED=1` with complete board profile.
- Both source-level variants built successfully in
  [ESCape32 CI #40735788893](https://github.com/cctsao1008/ESCape32/actions/runs/40735788893).
  The board profile is **SIM_ONLY**, uncalibrated OC/DAC thresholds;
  do **not** flash a hardware ESC.
- Separately compiled control had previously entered
  `am13e_app_motor_commutation_enable` ->
  `runtime_fault` -> `am13e_app_motor_fault_reset` immediately
  after positive DShot. This explains why source-built firmware
  is still **not** proven runtime equivalent to the pinned guest.
  A read-only SRAM safety-state diagnostic remains required.

## Safety, integration and P1 gates that must NOT be waived

- An `ival/4` early-capture threshold accepts faster acceleration
  but is **more vulnerable to switching-noise false CAP1** than
  `ival/2`. It needs a defensible speed/acceleration-dependent
  acceptance interval, not a hard-coded production-wide 1/4.
- Validate positive and negative transients, all original smoke/gentle/
  direct20/steps/100ms/500ms ramp cases, startup vs restart, CAP1
  phase-order, ADC comparator blanking, OC/nFAULT/OST hardware behavior,
  analog saturation, and both stable speed and torque direction.
- No change to original source baseline, pinned ELF hash, simulation
  acceptance gate or test criteria. Historical source drift and P1
  failures remain separate OPEN/FAIL issues.

**Recommendation:** use this as an isolated, causal
controller-design experiment. Do not merge production code based
on Direct20 alone or claim the whole system physically qualified.


## 2026-10-29 continuation: five-scenario and source-built safety diagnosis

- [Full 1,500ms Direct20 automated gate #40735921806](https://github.com/cctsao1008/escape32-qemu/actions/runs/40735921806) **SUCCESS** for the exact 9-byte candidate. This is a SIM_ONLY candidate A/B and does NOT change Original P1's pinned-ELF acceptance.
- [Five-profile external DShot source contract #40791543727](https://github.com/cctsao1008/escape32-qemu/actions/runs/40791543727) **SUCCESS**: `smoke`, `gentle`, `steps`, `ramp100`, `ramp500` static preboot FC stages match exactly the immutable source JSON profiles. No guest motor writes or manufactured sensor events.
- [Five-profile 1.5s-wide candidate A/B motor matrix #40791759457](https://github.com/cctsao1008/escape32-qemu/actions/runs/40791759457) remains **PENDING** as of this update; require every candidate to have 12 physical PWM_PAIR, CAP1_ACK and TIMG12_ACK, at least +50RPM, no significant powered-window reverse. No waivers to original P1.
- Separately source-built Motor Output=1 original-policy Control (distinct from pinned ELF) still enters `am13e_app_motor_commutation_enable()` -> `runtime_fault()` at the first positive DShot, with no CAP1/TIMG12. Read-only pre-fault marker recorded `audio_owner=0`, `safety_initialized=1`, `fault_latched=0`, `motor_timebase_running=0`. The Cortex-M33 compiler merges multiple failing guard branches to the same `0xA7CA` BL; the saved caller PC `0xA7CF` **cannot identify which later safety check returned false**.
- An explicitly SIM_ONLY `e62_sim_runtime_fault_reason` marker was added before **eight original enable/stop safety branches**. It records the failing branch without modifying the safety condition, OC/Trip state, GPIO/PWM output, Guest IRQ, or fault handler. Follow-up diagnostic CI is [#40792045153](https://github.com/cctsao1008/escape32-qemu/actions/runs/40792045153), not yet a motor PASS.
- All motor experiment build profiles explicitly require `AM13E_MOTOR_OUTPUT_CONFIGURED=1` or fail compilation. No real hardware board parameter, OC threshold or reset-inactive wiring has been qualified by these simulations.

Do not confuse **early-capture policy causal improvement**, **source-built electrical preflight availability**, **P1 strict**, and **hardware safety**: these are four independent gates.


## 2026-10-29 source-built Motor Output=1 validation (new)

The original ELF three-instruction experiment is now complemented by an
actual **source-built**, separately linkable ESCape32 pair (control and
3000us / quarter-window candidate); both use the exact same SIM_ONLY
Motor Output=1 board fixture. This builds the motor-control source code
directly rather than byte-patching the Original ELF.

- [Source-built Direct20 CI #40806638889](https://github.com/cctsao1008/escape32-qemu/actions/runs/40806638889): PASS experimental full-window, no significant negative rotor RPM.
- [Source-built five-profile CI #40806799665](https://github.com/cctsao1008/escape32-qemu/actions/runs/40806799665): five independent jobs PASS, all source-built Control/Candidate pairs, no candidate rotor RPM <= -50 during any full commanded positive window.

| Profile | Full positive commanded window | Candidate max RPM | Candidate significant reverse (<=-50 RPM) | Candidate physical PWM_PAIR |
|---|---:|---:|---:|---:|
| smoke | 1295 ms | 884.937 | 0 | 1552 |
| gentle | 2980 ms | 493.794 | 0 | 2257 |
| steps | 1500 ms | 1276.313 | 0 | 2739 |
| ramp20_100ms | 1095 ms | 885.278 | 0 | 1914 |
| ramp20_500ms | 1495 ms | 885.550 | 0 | 2330 |

Original-policy source-built controls have severe reversal in some
profiles and insufficient closed-loop switching in others. The
candidate uses identical front-end/Guest board definitions and includes
real CAP1 and TIMG12 feedback, not host-injected commutations.

**Crucial scope:** The above QEMU analog frontend assumes an
uncalibrated 1.65V zero-BEMF reference (code 2048 on a 3.3V/12bit ADC),
0.02 V per modeled BEMF volt. The OC comparator thresholds, power
stage and startup rotor angle are also SIM_ONLY assumptions; this is
not measured ECX87 analog-electrical validation. A CI experiment's
success does not promote an original ELF P1 FAIL to PASS.

An additional six-scenario test on the exact three-instruction
non-original ELF, using the existing unchanged Native P1 scenario
JSONs and the unchanged strict P1 analyzer, runs separately on
[CI #40808471350](https://github.com/cctsao1008/escape32-qemu/actions/runs/40808471350).
Because the Guest SHA is *not* Original Rel17.3, the original P1
analyzer must continue to reject it; the report distinctly classifies
physical behavior and the unwaived SHA provenance gate.
