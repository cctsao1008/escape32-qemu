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

**Qualification: OPEN** until these commands run successfully against the exact original Guest ELF. A Python unit-test PASS does not prove original Guest decoding.

Legacy `g13b_native_dshot.py` with **no** `--input-config` intentionally keeps **DSHOT600** to preserve G13B1 and CI baseline behavior.

## Deliberately not changed in phase 1

- Existing T01/T02 (`tests/functional_dshot_sitl.py` and `scenarios/e62-dshot-v1.json`) and QEMU autonomous SITL still use DShot600. They need a separate compatible protocol-selectable runtime integration before claiming DShot300 scenario support.
- External BEMF/VN-to-ADC generation, PWM six-pad observation and sustained functional commutation are independent work items.
- No firmware ELF modification, fake RX/IRQ/capture or strict-gate waiver.
