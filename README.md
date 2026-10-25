# escape32-qemu

TI AM13E23019 QEMU model and original ESCape32 Rel17.3 Firmware Software-In-The-Loop (SITL).

**Current functional baseline: G13B7.1.** Original Guest DShot600 receive,
CRC, PWM, CMPSS/ECAP, TIMG12 and zero-throttle teardown are exercised
through QEMU virtual hardware stimulus. The 11s T01 scenario (11,000
frames) has a verified aggregate-functional PASS with Ramp/Hold sampled
Stage PASS. Scripted BEMF is **not** rotor physics, motor RPM, thrust,
flightworthiness or real electrical/thermal qualification.

**Independent strict-gate status:** Historical G13B3L six-sector Native
gate previously PASS; G13B3M twelve-sector rotor stability is **known
FAIL** and remains a separately blocking test. T02 110s is not yet
independently qualified.

## Documentation

- [System architecture and stable APIs](docs/current/architecture.md)
- [Test/CI matrix and honest gate meanings](docs/current/test-matrix.md)
- [Functional SITL G13B7.1](docs/current/functional-sitl.md)
- [Full document index](docs/README.md)
- [Original G0–G13B development log](docs/history/README-development-log.md)
- [Immutable paired binaries and licenses](baseline/e62-g13b3/README.md)

## Build and test (Ubuntu / WSL)

```bash
git submodule update --init qemu
./build.sh
bash tools/ci/check_autonomous_host.sh
mkdir -p artifacts
python3 tools/native_sim_cfg_flash.py --sim-only-opt-in \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --output artifacts/e62-g13b3-functional-cfg-flash.bin
```

Run the 11s full T01 with the **canonical** CLI:

```bash
set -o pipefail
/usr/bin/time -p python3 tests/functional_dshot_sitl.py \
  --autonomous --autonomous-telemetry-interval-ms 200 \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-functional-cfg-flash.bin \
  --plan scenarios/e62-dshot-v1.json --id T01 \
  --artifact artifacts/e62-t01-full.json \
  2>&1 | tee artifacts/e62-t01-full.log
```

Historical CLI `tests/g13b4_functional_dshot_sitl.py` remains a
compatibility wrapper with the **same** implementation.
Historical G13B3 probe `tests/g13b2_native_drive_probe.py` keeps its
original CLI and imported names. No original ELF or board-register
programming contract was rewritten by the repository refactor.

## Source organization

- `machine/`: main SoC model plus focused BEMF, DShot, Trip and PWM includes.
- `tools/native_arming.py`: source-qualified Rel17.3 WFI and genuine
  physical Zero-DShot ARM path, reexported from the historic probe.
- `tools/sitl_autonomous_transport.py`: QEMU MMIO and Stage checkpoints.
- `tools/sitl_autonomous_evidence.py`: read-only Guest samples and timing.
- `tools/sitl_stage_oracle.py`: sampled CRC/Throttle/PWM Stage policies.
- `tools/autonomous_sitl_host.py`: **compatibility facade only**.
- `tests/functional_dshot_sitl.py`: current SITL CLI / Native Runner.
- `tests/`: board, Guest integration and Host regression tests.
- `scenarios/`: reproducible DShot input plans.
- `baseline/`: pinned original ELF/QEMU, manifest, checksums and notices.
- `.github/workflows/`: independent functional, historical strict,
  pinned binary and Host model gates.

The host QEMU binary in the historical pinned baseline targets
Ubuntu 24.04 and must not be assumed compatible with Ubuntu 22.04 WSL.
