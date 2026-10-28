# E62 Host CI recovery and P1 evidence boundaries — 2026-10-28

## Scope / non-negotiable conditions

- Original ESCape32 Rel17.3 ELF SHA256:
  `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`
- No firmware, Motor Plant, native P0/P1 acceptance-gate, or electrical
  current/torque model modification is claimed by the changes here.
- Distinguish **test-harness regression**, **historical binary/source pairing**,
  **source-only Observer equivalence**, **P0 SIM_ONLY**, and **P1 rotor stability**.
  A PASS in one does not grant any other qualification.

## 1. Resolved: Host CI source-text false positive

Before: `tests/test_e62_native_no_wfi_liveness.py` used
`assertNotIn('gdb', inspect.getsource(run).lower()...)`. That
incorrectly rejected a comment or the provenance field
`used_guest_wfi_or_gdb=False`, even when the runner used no GDB.

Commit
[`aedc025aae258f1ccb6787489cd349fae8f2e176`](https://github.com/cctsao1008/escape32-qemu/commit/aedc025aae258f1ccb6787489cd349fae8f2e176)
replaced the substring heuristic with Python AST checks for executable
GDB launch flags and actual literal QTest clock/IRQ commands, and added
negative-control tests for `-gdb`, `-s`, `clock_step`, and
`clock_step_next`. An initial `-S` in the separately opted-in
preboot diagnostics is not itself a GDB connection.

CI
[#40705854856](https://github.com/cctsao1008/escape32-qemu/actions/runs/40705854856):
**PASS_G13B3_HOST_ONLY_UNIT_REGRESSIONS**. This corrects the host test
contract, not the P1 motor behavior. The AST check is source-static,
not a proof of runtime isolation from all possible external processes.

## 2. Historical archive integrity is not current source pairing

The original `tools/e62_pinned_baseline.py verify` requires
`manifest.json:qemu.source_tree_sha256` to equal **current**
`SOURCE_FILES`. Machine sources have evolved since publication;
the original verifier still intentionally returns
`Pinned QEMU/Guest build source drift: republish binary pair`.
**Do not** rewrite the manifest, bless a new QEMU, update the stored
hashes, or bypass `verify` merely to make CI green.

Two distinct read-only checks already exist:

1. `.github/workflows/e62-pinned-archive-integrity.yml`:
   bit-exact **archived ELF/QEMU/libfdt** integrity only (not current
   source pairing). Archived CI
   [#40697697733](https://github.com/cctsao1008/escape32-qemu/actions/runs/40697697733)
   completed successfully.
2. `.github/workflows/e62-pinned-source-drift-diagnostic.yml`:
   explicit historical-versus-current source hash drift, with no waiver
   and no binary republication. This is diagnostic even when green.

The old strict pinned regression remains red on source identity by
design; its `12-sector / 90ms` acceptance gate also remains independent.

## 3. Source-only Focus Observer evidence (NOT P1)

[CI #40700986752](https://github.com/cctsao1008/escape32-qemu/actions/runs/40700986752),
Attempts **1 and 2**: complete
`RR record-seed → replay OFF-A → replay OFF-B → replay ON` both PASS.

- Independent RR seed SHA256 prefix:
  `03640956b1cfdaa6` and `645dc742eb58bdee`.
- Both OFF/OFF and OFF/ON comparisons: 28,879 **original** events
  bit-exact per attempt, including virtual timestamps and six source
  fields, through 2990 ms.
- Source ENERGY delta identical within each attempt; 1,512
  `SWITCH_FOCUS` records added in the bounded 2795–2840 ms ON window.
- Result: `SUPPORTED_FOR_THIS_REPLAY_ONLY`.
- No QTest/QMP in flight, no virtual-time step or Guest memory write.
- **No Motor P1 PASS, no general unsynchronized-QEMU determinism claim.**

## 4. Current P1 strict failures: separate phenomena

The latest checked dedicated native P1 matrix was
[#40697697816](https://github.com/cctsao1008/escape32-qemu/actions/runs/40697697816).
Existing read-only source analyzers emitted:

| Scenario | Analyzer | Direction changes | Key early observation |
|---|---|---:|---|
| smoke | PASS | 0 | Pre-TIMG12 peak current 0.448 A |
| gentle | PASS | 0 | Pre-TIMG12 peak current 0.435 A |
| direct20 | FAIL | 337 | Negative torque at +5.20988 ms; reverse >50RPM at +7.20988 ms; first TIMG12 at +13.742272 ms; pre-TIMG12 peak current 45.463 A |
| steps | FAIL | 223 | Significant direction reversal (not conclusively localized by initial 12 rotor samples) |
| ramp20_100ms | FAIL | 238 | Significant direction reversal |
| ramp20_500ms | PASS | 0 | Smooth-ramp comparator; not a product acceptance waiver |

**Independent artifact cross-check:** In the original CI
`e62-native-p1-scenario-suite` artifact, the full
`e62-p1-script-direct20.p1.json` records exactly **3300/3300**
DShot source frames, `dshot_first_mismatch=null`, 0 invalid BEMF
samples and 0 invalid overcurrent samples *under this SIM_ONLY
sampling contract*. It also records 169 original Guest closed-loop
PWM pairs, 253 CAP1 W1C acknowledgments, and 168 TIMG12 W1C
acknowledgments. Thus the failed directional startup was **not
classified by those audits as missing DShot frames or a missing
CAP1/TIMG12 source path**. None of these counters validates electrical
analog accuracy, independent QEMU determinism or physical motor
stability.

**Time origin:** The `direct20` times are relative to first
power-pair/rotor source observations reported by
`tools/native_p1_pre_feedback_geometry.py`, not an absolute QEMU
boot timestamp. The first negative torque/reverse samples **precede**
the first TIMG12. This establishes that subsequent TIMG12 period
programming cannot be the *sole initiating cause* of that trace,
but does **not** uniquely establish firmware versus physical-model
responsibility.

A separate current-QEMU strict rotor test
[#40697697932](https://github.com/cctsao1008/escape32-qemu/actions/runs/40697697932)
stopped at 8 completed powered feedback sectors and 65.481790 ms
integrated. The fail-closed diagnostic classified
`ANALOG_FRONTEND_SATURATION`: synthetic BEMF V phase
+90.026 V at ~6154.7 simulated RPM mapped to +3.4505 V on a
3.3 V ADC fixture (the input gain and offset were
0.02 V/V and 1.65 V respectively). The tool explicitly did **not**
clip or bypass the overrange. This is a separate, unqualified
SIM_ONLY analog-fixture boundary, not evidence that physical silicon
has those exact voltages or that the original Guest is wrong.

The strict rotor history also contains model-energy diagnostics with
nonzero topology projection impulse. Those historical sampled-hold
diagnostics cannot establish the current physical switch-level
model's energy correctness; do not merge them into the Observer
equivalence PASS.

## 5. Next technical checks (read-only first)

1. **Pre-first-TIMG12 direct20:** use existing
   `tools/native_p1_pre_feedback_geometry.py` and original
   `ROTOR`/`SWITCH`/`PWM_PAIR` source to align commanded
   fixed-startup vector, measured rotor electrical position,
   phase current, reconstructed torque sign and the first
   `CAP1/CMP_FILTER/TIMG12` source timestamps. Never infer
   a fabricated switching event or silently integrate beyond the
   available data.
2. **Ramp-rate counterfactual:** compare unchanged original
   `direct20`, `ramp20_100ms`, `ramp20_500ms` input
   configurations with *identical* ECX87 motor parameters. Determine
   whether torque reversal is already triggered before the first
   valid feedback loop and whether the reduced initial current
   prevents that event. Ramp pass is evidence of sensitivity, not proof
   of a specific physical root cause.
3. **Analog boundary:** independently verify with a sourced
   motor/electrical frontend specification before changing
   `input_gain_v_per_bemf_v`, ADC scale or model limits.
   Preserve the current fail-closed `ANALOG_FRONTEND_SATURATION`
   result; never insert an undocumented clamp.
4. **Only after evidence:** propose one physical-model or
   firmware-porting hypothesis at a time, with strict P0, P1,
   source-causality and negative-control reruns. Do not
   rewrite Original Rel17.3 ELF, weaken gate requirements,
   or label SIM_ONLY outcomes hardware qualified.

## Acceptance state

- Host-only CI: **PASS** at `aedc025a`.
- Archived binary bytes: **historical integrity PASS only**.
- Current-source/historical pinned QEMU pairing: **NOT ESTABLISHED**.
- Focus Observer source equivalence: **PASS for two independent replay seeds**.
- Original-Guest P0 SIM_ONLY: separately passed in prior runs;
  not requalified by this report.
- Motor P1 strict startup/stability: **OPEN / FAIL**.
- Real ECX87 ESC motor hardware: **NOT QUALIFIED**.
