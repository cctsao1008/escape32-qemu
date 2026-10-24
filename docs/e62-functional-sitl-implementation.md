# E62 Functional SITL — T01/T02 Implementation (experimental v0.1)

## What this package implements

- `scenarios/e62-dshot-v1.json`: source scenario specification (T01/T02).
- `tools/functional_dshot_scenario.py`: fail-closed, integer-nanosecond schedule for 1 kHz DShot600. Stream 11,000 T01 or 110,000 T02 commands without holding full packet buffers in memory. Zero is DShot 0; positive percentage maps to data 48–2047.
- `tools/compile_dshot_scenario.py`: offline scenario preview and bounded JSON export. **This does not execute QEMU.**
- `tools/functional_bemf.py`: deliberately artificial comparator stimulus. For the Guest-selected phase and edge polarity, produces alternating voltage samples across the **Guest-observed active comparator DAC threshold**. No rotor model, torque, RPM or physical power claim.
- `tests/g13b4_functional_dshot_sitl.py`: **experimental** native bridge. Reuses original Rel17.3 WFI role proof, neutral-250ms arming, existing external PA26 DShot600 wire, original Guest BEMF arm/readiness and QEMU `SIM_BEMF_INPUT` MMIO. Captures Guest CRC-feed count, throttle, native PWM, CAP1 and TIMG12 service counters. Full acceptance requires original neutral teardown. This specific integrated runner has not been executed against the user's installed QEMU yet.
- `tests/test_functional_*.py`: host-only deterministic tests.

## Safety / provenance

- The scenario uses the pinned original ELF SHA-256 `05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`. The runner refuses a different firmware image.
- Pre-CPU SIM_ONLY factory `Cfg` is supplied via existing QEMU loader at Flash `0x4000` and must match its readback.
- Runtime QTest writes: external PA26 DShot edge queue and three-channel SIM_ONLY analog input only. Existing pre-start external overcurrent fixture reset is performed as in G13B2. No guest memory, injected CAP1, forced ISR, guest PWM/Gate/Trip manipulation.
- No physical motor qualification, no actual RPM claim, no weakening/changing the separate G13B3M strict rotor gate.
- Validating *the planned frame schedule* is not the same as validating *each packet's original Guest CRC acceptance*. Native runner checks Guest source counters and records transitions; source failures must remain FAIL or OPEN.
- The QEMU / glibc linkage must be checked independently. On Ubuntu 22.04, use a compatible **local source-built custom AM13E QEMU** for development; do not label its result as an execution of the Ubuntu 24.04 pinned QEMU binary. Original firmware SHA remains checked.

## Unit tests (no QEMU required)

```bash
cd ~/github/escape32-qemu
python3 -m unittest discover -s tests -p 'test_functional*.py' -v
python3 tools/compile_dshot_scenario.py \
  --plan scenarios/e62-dshot-v1.json --id T01 \
  --output artifacts/e62-functional-t01-schedule.json
python3 tools/compile_dshot_scenario.py \
  --plan scenarios/e62-dshot-v1.json --id T02 \
  --output artifacts/e62-functional-t02-schedule.json
```

## First Native smoke — Ubuntu 22.04 development build

Use ONLY the exact original Guest ELF under `baseline/.../firmware/`. Existing pre-boot fixture may already exist; regenerate from the original ELF for provenance:

```bash
cd ~/github/escape32-qemu
mkdir -p artifacts
python3 tools/native_sim_cfg_flash.py --sim-only-opt-in \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --output artifacts/e62-functional-cfg-flash.bin

python3 tests/g13b4_functional_dshot_sitl.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-functional-cfg-flash.bin \
  --plan scenarios/e62-dshot-v1.json --id T01 \
  --max-frames 50 \
  --artifact artifacts/e62-functional-t01-smoke.json \
  2>&1 | tee artifacts/e62-functional-t01-smoke.log
```

`--max-frames 50` stops after 50 scheduled virtual-time frames, not 50 host milliseconds. **This is intentionally `OPEN_BOUNDED_SMOKE_NOT_FULL_DURATION` and exits nonzero**; it must not print/claim `PASS_FUNCTIONAL`. Read `artifacts/e62-functional-t01-smoke.json` and logs first. A pre-Gate/arming/error failure is an actual FAIL, not an acceptable partial smoke.

If and only if that proves original DShot wave delivery, native CRC progress and safe BEMF route, attempt full T01 by **removing `--max-frames 50`** and writing a new artifact. Full T02 is longer (110 s of virtual time; performance may be substantial). The 1 kHz schedule is a planned test default, not a performance promise; missed guest-time deadlines fail closed.

## Native acceptance per stage

- Observed external DShot values/cadence and original `valid_frame_feeds` progress.
- Guest-owned `throt` updates, no unplanned CPU fault.
- For positive stages: qualified six native PWM outputs and Gate/Trip; nonzero original CAP1 capture and TIMG12 serviced counters.
- Scripted comparator stimulus counted independently, and `throt=0` must be accepted during valid neutral-frame teardown.
- Stage verdicts live in JSON; if evidence is missing, `FAIL` or `OPEN`, never synthetic physical RPM or G13B3M rotor PASS.

## Important limitation

The new Native runner is *not yet tested against the actual local QEMU/ELF pair*. It is a first integrated candidate, not a certified functionality claim. The synthetic BEMF waveform is deliberately a test fixture tied to real Guest-selected comparator polarity and phase, not evidence that any physical motor responds to duty. Timing (`--bemf-crossing-delay-us`) may need adjustment based on original Guest early-edge policy, using source-owned CAP1 rejection evidence; never write CAP1 or force its ISR.
