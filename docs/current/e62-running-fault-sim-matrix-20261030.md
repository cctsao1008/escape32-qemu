# E62 Issue #7 — SIM_ONLY Running Fault Matrix (2026-10-30)

## Scope / decision
Software-only qualification for the **configured virtual protection design**:
current-sensor overrange OC U/V/W (simulated, *not true motor current*),
PA22 nFAULT, and DShot source loss→WWDT. No real hardware criterion.
Original Rel17.3 Guest pinned to
`05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.
No Guest ISR, PWM, Trip, or CAP1 register injections, and no fake WFI/GDB.

## Actual QEMU execution matrix (current-source negative oracle)

| Motor | Fault | Source→ comparator→OST3→six off→latch after release | Evidence |
|---|---|---|---|
| ECX87 KV147 | OC-U | PASS | [#41075503856](https://github.com/cctsao1008/escape32-qemu/actions/runs/41075503856) |
| ECX87 KV147 | OC-V | PASS | same |
| ECX87 KV147 | OC-W | PASS | same |
| ECX87 KV210 | OC-U | PASS | same |
| ECX87 KV210 | OC-V | PASS | same |
| ECX87 KV210 | OC-W | PASS | same |

This run is after `b759344`, the strict independent 3000 DShot
source-frame/virtual-timestamp/OC-edge audit. Its
`PASS_SIM_NATIVE_QEMU_PROFILE_OC_6_OF_6` log line came from
actual QEMU with the *Original Guest*, not a mocked unit test.

| Scenario | Status | Evidence |
|---|---|---|
| PA22 external nFAULT→OST2, six off, no auto-rearm | PASS | [#41060908950](https://github.com/cctsao1008/escape32-qemu/actions/runs/41060908950) |
| External DShot loss→original WWDT BOOTRST | PASS | same |
| Missing / forged OC edge or wrong phase | PASS as rejection negative unit test | `tests/test_e62_native_running_oc_sense.py` |
| Source command modification / stale or gapped FC time | PASS as rejection negative unit test | same |
| Trip latch lost / six gates not off / late PWM | PASS as rejection negative unit test | same |
| No powered pre-fault PWM / source while neutral | PASS as rejection negative unit test | same |
| Unsupported motor/profile or fake fault waiver | PASS as rejection negative unit test | `tests/test_e62_sim_model_profile.py` |
| UV voltage threshold/source | NOT_MODELED | `configs/e62-sim-profile-matrix-v1.json` |
| OV voltage threshold/source | NOT_MODELED | same |
| Thermal source and trip | NOT_MODELED | same |

The simulator's **current virtual design does not claim UV, OV or
thermal protection**. These are *unimplemented SIM sources*, not
approximated evidence of functioning safety protection. If a later
virtual design chooses to require them, they become separate
implementation/qualification gates and must not inherit this PASS.

## Safety and evidence interpretation
- A negative unit test passes only if corrupted evidence produces a
  **FAIL** verdict; it never substitutes for positive real-QEMU tests.
- P1 startup/near-stall/reacquisition is tracked separately in #5.
  OC fault qualification does not imply stable forward rotor drive.
- No actual motor current limit, power driver, or board protection
  characteristic is inferred from the synthetic ADC-like OC source.
- Main current QEMU pin-mismatch and strict rotor functional
  failures remain unwaived, outside this narrow running **source-fault
  mechanism** matrix.
- Re-run full QEMU suite after model/protection implementation changes.

## CI
- [#41075503856](https://github.com/cctsao1008/escape32-qemu/actions/runs/41075503856):
  **SUCCESS** actual 6/6 native QEMU current-source overrange.
- [#41060908950](https://github.com/cctsao1008/escape32-qemu/actions/runs/41060908950):
  **SUCCESS** original nFAULT/WWDT.
- [#41076529941](https://github.com/cctsao1008/escape32-qemu/actions/runs/41076529941):
  updated unit negative/profile checks **PASS**; full QEMU status to
  confirm before issue closure.
