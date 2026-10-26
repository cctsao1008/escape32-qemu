# E62 ESC Functional Input Configuration — Phase 1

The new external input config is `configs/e62-functional-input.json`, defaulting to **DSHOT300**.

```json
{
  "schema": "e62.esc-input.v1",
  "protocol": "DSHOT300",
  "dshot": {"frame_rate_hz": 1000},
  "pwm": {"pulse_width_us": 1500}
}
```

Selectable protocol names: `DSHOT150`, `DSHOT300`, `DSHOT600`, `PWM`.

- DShot150/300/600: generate **32 actual PA26 wire transitions** per CRC-protected packet through QEMU's existing SIM_ONLY PA26 scheduler, with 100 MHz TIMG4 tick-quantized pulse widths. Original Guest TIMG4/DMA/CRC decides whether each configured bitrate is supported.
- Servo `PWM`: **configuration reserved only**. The native DShot receiver explicitly rejects this choice until a separate servo pulse input and Original Guest validation exist. Never remap PWM to DShot.
- The 1 kHz `frame_rate_hz` is reserved for the continuous functional command stream; the phase-1 native test sends **one packet**, so do not claim that it validates continuous 1 kHz transmission.

## DShot300 original Guest one-packet probe

```bash
python3 tests/g13b_native_dshot.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --input-config configs/e62-functional-input.json \
  --throttle 1000 \
  --artifact artifacts/e62-dshot300-rx.json
```

Run the same command with `--corrupt-crc` and a separate artifact to perform the physical-wire CRC-negative test.

**One-packet DShot300 native qualification: CONFIRMED.** User-run original Guest logs prove a CRC-valid `0x7d0a` packet (32 captures and DMA beats, callback return 1, decoded throttle 953 from DShot value 1000), and a CRC-invalid `0x7d0b` packet (return 0, no valid feed, throttle unchanged). These do NOT establish repeated packets or closed-loop PWM.

Legacy `g13b_native_dshot.py` with **no** `--input-config` intentionally keeps **DSHOT600** to preserve G13B1 and CI baseline behavior.

## Functional SITL DShot300: wired, not yet qualified

The `tests/functional_dshot_sitl.py` per-WFI runner now accepts `--input-config`. The configured physical bitrate is used for **the original Guest's 250ms physical zero-throttle ARM**, scripted command frames, and zero-command teardown.

The existing `scenarios/e62-dshot-v1.json` still supplies **T01/T02 throttle intentions, 1kHz cadence, and payload mapping**. Its legacy DShot600 label is superseded **only for the physical signal** when `--input-config` is explicit. Artifacts record `external_input_protocol` to prevent ambiguous qualification.

```bash
mkdir -p artifacts
python3 tools/native_sim_cfg_flash.py --sim-only-opt-in \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --output artifacts/e62-g13b3-functional-cfg-flash.bin

# Bounded diagnostic smoke: expected OPEN_BOUNDED_SMOKE_NOT_FULL_DURATION,
# with process exit 1; intentionally NEVER a functional PASS.
python3 tests/functional_dshot_sitl.py \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-functional-cfg-flash.bin \
  --plan scenarios/e62-dshot-v1.json --id T01 \
  --input-config configs/e62-functional-input.json \
  --max-frames 100 \
  --artifact artifacts/e62-t01-dshot300-smoke.json
```

For a full T01 qualification, omit `--max-frames 100`. Do not borrow the DShot600 T01/T02 PASS results to claim DShot300.

**Autonomous QEMU Functional SITL remains DShot600-only**. Combining `--autonomous` with DShot300 is rejected at CLI validation until the QEMU timer sender is upgraded. Legacy invocation without `--input-config` remains unchanged.

## Pending integration

- DShot300 Guest ARM and sustained functional T01: **OPEN** until run.
- Independent three-phase BEMF and **VN** voltage source feeding both Comparator and ADC: **OPEN**.
- Guest PWM output history and correct phase-sequence verification, independent of Guest-selected Comparator phase: **OPEN**.
- No ELF modification, guest register/SRAM spoofing, artificial CAP1/TIMG12/IRQ or G20 strict-gate waiver.
