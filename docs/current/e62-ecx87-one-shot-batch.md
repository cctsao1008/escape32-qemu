# E62 EC 87 KV210 — One-command 12S-reference electrical BEMF campaign

**Entrypoint**

```bash
cd ~/github/escape32-qemu
git pull --ff-only
bash tools/run_e62_ecx87_frequency_batch.sh
```

The script first provisions **42 poles (21 pole pairs)** from the unchanged pinned original Rel17.3 ELF into a **SIM_ONLY preboot Cfg Flash**. This is the repo's existing `tools/sim_motor_cfg.py` functionality, **not** original Guest UART CLI execution.

Next the script executes **three independent QEMU Guest runs** with external physical-format PA26 DShot300, original Guest CRC and arming, fixed-frequency phase-independent U/V/W BEMF at **900, 1040 and 1285 electrical Hz**, and the existing source-pinned six-pad `--six-phase-audit` for the full **11-second** T01 (1-second ramp to 90%, 10-second 90% hold). Each frequency uses a separate config, original Guest instance, JSON evidence, and text log. Sector audit storage is explicitly capped at 100000 records to cover the theoretical high-frequency T01 envelope rather than the older 20000-sector default.

| External BEMF | Input eRPM | 21-pole-pair RPM equivalent |
|---:|---:|---:|
| 900 Hz | 54,000 | 2,571.43 RPM |
| 1040 Hz | 62,400 | 2,971.43 RPM |
| 1285 Hz | 77,100 | 3,671.43 RPM |

Generated files are under `artifacts/e62-ecx87-kv210-full-batch/`:

- `e62-g13b3-ecx87-kv210-cfg-flash.bin` (verified pre-boot Cfg)
- `e62-dshot300-<hz>-hz-bemf.json`
- `e62-dshot300-<hz>-hz-evidence.json`
- `e62-dshot300-<hz>-hz.log`
- `e62-dshot300-<hz>-hz-exit-code.txt`
- `batch-summary.json` (separate per-point verdicts and aggregate)

Any child test nonzero exit or incomplete/malformed evidence is marked **FAIL**. The batch continues to gather all three results and finally exits nonzero if any functional test fails, **or** if a separate provisional **±10% average commutation-rate screening** mismatches the ideal 6 sectors per electrical cycle. This screening is not an ESC spec and does **not** establish phase lock or rotor tracking even if it passes; examine `all_functional_points_pass` and `all_average_rate_screens_match` independently. Never reinterpret a full SITL functional PASS as a frequency-tracking PASS.

The simulator does **not** currently emulate a physical 12S LiPo voltage / propeller-load curve in this independent BEMF fixture. It does not change the original Guest motor-control tuning or protection thresholds. Only `telem_poles` changes in the simulated Config Flash. The new batch has been committed but has **not yet been executed with the user's pinned QEMU**; its PASS status must come from the generated Guest-backed evidence, not this file.

To review the aggregate:
```bash
jq '{overall_status, all_functional_points_pass, all_average_rate_screens_match, points: [.points[] | {electrical_hz, original_guest_functional_status, six_phase_sector_count, hold_timg12_services, observed_average_commutation_to_ideal_ratio, rate_screen_only_10percent}]}' artifacts/e62-ecx87-kv210-full-batch/batch-summary.json
```
