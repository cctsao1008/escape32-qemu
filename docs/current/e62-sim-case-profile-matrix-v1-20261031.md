# E62 #5 — Versioned Simulation Case Profiles v1 (2026-10-31)

**Scope: SIM_ONLY. Firmware is the DUT, NOT a variable to tune for SITL.** Original Rel17.3 immutable ELF SHA-256 `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`. Hardware signoff and autonomous re-acquisition are **not** established by a profile being well-formed, by correct QEMU readback, or by a successful unit test.

Canonical machine-readable profile registry: [`configs/e62-sim-case-profiles-v1.json`](../../configs/e62-sim-case-profiles-v1.json). Strict parser/resolver/host readback oracle: [`tools/e62_sim_case_profiles.py`](../../tools/e62_sim_case_profiles.py).

## Explicit versioned model identities

| Profile ID | QEMU native model | Bus | Motor | Propeller load | Effective total inertia | Classification |
|---|---|---:|---|---|---:|---|
| `BASE-KV147-24V-NOPROP` | `ecx87-kv147` | 24 V | maxon EC87 KV147 | None | 1× published bare rotor J | **Historical motor-only baseline**, unchanged |
| `BASE-KV210-24V-NOPROP` | `ecx87-kv210` | 24 V | maxon EC87 KV210 | None | 1× published bare rotor J | **Historical motor-only baseline**, unchanged |
| `QB-KV210-47V-APC24X12E-J1` | `ecx87-kv210-apc24x12e-47v-j1` | 47 V | maxon EC87 KV210 | APC 24×12E analytical static V=0 | 1× J_m | Product **simulation sensitivity**, no additional prop inertia |
| `QB-KV210-47V-APC24X12E-J2` | `ecx87-kv210-apc24x12e-47v-j2` | 47 V | maxon EC87 KV210 | APC 24×12E analytical static V=0 | 2× J_m | Product **simulation sensitivity**, assumed prop J = 1× J_m |
| `QB-KV210-47V-APC24X12E-J5` | `ecx87-kv210-apc24x12e-47v-j5` | 47 V | maxon EC87 KV210 | APC 24×12E analytical static V=0 | 5× J_m | Product **simulation sensitivity**, assumed prop J = 4× J_m |

Here `J_m=0.00013 kg·m²`, and `J_total = J_m + J_prop`. J1/J2/J5 are *hypothetical* total inertias and **must never** be presented as measured blade/hub inertia. Published 47 V operating condition is distinct from model validity at that voltage; the simulated analog, driver, temperature, load and airflow are not calibrated to the vehicle.

Sources: maxon EC 87 flat UAV April 2025 datasheet, p.1; [APC analytical data `PER3_24x12E.dat`](https://www.apcprop.com/files/PER3_24x12E.dat), v2022-0915, simulated on 2022-09-22, 0 mph static rows. Below 1000 RPM the torque curve uses a declared quadratic approximation; above 6000 RPM, the plant rejects unsupported values. Reverse torque symmetry is **not** manufacturer-verified windmilling behavior.

## Independent coast/DShot case profiles

Every model is paired with the **same pinned Original Guest** and exactly one source-owned external-FC DShot600 scenario (1 kHz PA26 wire source; Guest readiness NEVER gates the frames):

| Case | Scenario file | DShot: neutral / 20% / neutral coast / 20% / neutral | Source frames |
|---|---|---|---:|
| C300 | `scenarios/e62-experimental-two-demand-coast-short300.json` | 1500 / 1500 / **300** / 1500 / 300 ms | 5100 |
| C1500 | `scenarios/e62-experimental-two-demand-coast-medium1500.json` | 1500 / 1500 / **1500** / 1500 / 300 ms | 6300 |
| C3000 | `scenarios/e62-experimental-two-demand-coast-long3000.json` | 1500 / 1500 / **3000** / 1500 / 300 ms | 7800 |

**Total: 5 × 3 = 15 separately identifiable SIM_ONLY cases.** Profile existence does not imply a case has been run or passed. Normal push CI currently selects three APC models × C300; the GitHub workflow's manual `coast_ms` choice allows selecting C1500 or C3000 without changing any case/firmware parameters. Baseline profiles are preserved and available to the same resolver for independent comparison.

## Running and validating a case

Strict source/profile preflight, no QEMU launch:

```sh
python3 -m unittest discover -s tests -p test_e62_sim_case_profiles.py -v
python3 tools/e62_sim_case_profiles.py
python3 tools/e62_sim_case_profiles.py --profile-id QB-KV210-47V-APC24X12E-J2 --coast-ms 1500
python3 tools/e62_sim_case_profiles.py --profile-id QB-KV210-47V-APC24X12E-J2 --coast-ms 1500 --field qemu_motor_profile
python3 tools/e62_sim_case_profiles.py --profile-id QB-KV210-47V-APC24X12E-J2 --coast-ms 1500 --field scenario_path
```

Actual QEMU (via CI workflow) always uses **read-only QTest numeric effective readback**, not just the selected profile string. Must match Kv, phase R/L, Kt, VBUS, initial pose, APC load enable, total inertia and J ratio, real DShot frames/sha and original immutable ELF SHA.

Example post-run source validation (readback success is *not* reacquisition success):

```sh
python3 tools/e62_sim_case_profiles.py \
  --profile-id QB-KV210-47V-APC24X12E-J2 \
  --coast-ms 1500 \
  --evidence artifacts/e62-apc24x12e/QB-KV210-47V-APC24X12E-J2-1500.json \
  --output artifacts/e62-apc24x12e/QB-KV210-47V-APC24X12E-J2-1500-profile-readback.json
```

The **unchanged** `tools/native_p1_qualification.py` runs separately and its failure must propagate to the actual QEMU job status. No direct Guest register writes, model-angle leaks, synthetic CAP1, WFI or GDB. A SIM_ONLY safe refusal does NOT count as successful second-demand takeover. Distinct source conditions may produce distinct outcomes and must not overwrite historical failures.

## Known restrictions

- APC 24×12E data are analytical static estimates, not propeller inertia, negative windmilling curves, or bench calibration.
- QEMU model is a research model with stated analog/current/driver assumptions; model provenance and empirical correctness are separate questions.
- Product/hardware acceptance is not claimed from simulation.
- The existing Issue #5 300ms significant reversal counterexample remains FAIL until a source-backed, independently reviewed result establishes otherwise.
- **Firmware may change only for a separately proven firmware bug, never to accommodate SITL.**
