# Current Functional SITL — G13B7.1

Run `tests/functional_dshot_sitl.py` (historic G13B4 alias retained).
Pinned ESCape32 Rel17.3 ELF SHA256:
`05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0`.

## Input and scope

T01: 1,000 physical 1kHz DShot600 frames during ramp 0→90%,
followed by 10,000 frames / 10 seconds hold. QEMU 750us scripted BEMF
crossings are test stimulus **not rotor physics**. QEMU SIM_ONLY MMIO
starts at 0x5ffea000; ABI 4 must fail closed on an old QEMU.

Original Guest owns DMA, valid CRC feeds, 250ms neutral ARM release,
CMPSS/ECAP/TIMG12 and PWM control. Runtime GDB WFI breakpoints are not
used; number of original Guest WFI executions is NOT_MEASURED.

## Acceptance

- Physical stage-end DShot counts and boundaries latched in QEMU.
- Aggregate source CRC acceptance ratio regression floor >=90%.
- Ramp/Hold **non-coherent sampled** Guest throttle/CRC/CAP1/TIMG12
  progression; differential PWM high/low duty.
- All six comparator MUX/polarity states during positive Hold; state
  coverage does not prove sector ordering.
- BEMF -> CAP1 -> TIMG12 temporal event association (not ISR causality).
- Source-owned original Guest neutral teardown; zero unresolved faults.

JSON obsolete per-WFI Stage fields are `null`, never fake zeroes.
`autonomous.host_perf_profile` captures attributed Host wall regions,
while `simulator_workload_profile` holds **counts**, not CPU time.

This is a **functional software-in-the-loop** gate, not closed-loop
physics, real rotor direction, per-packet receive CRC or silicon proof.
G13B3M rotor reversal remains independent known FAIL.

[Build and full T01 command](../../README.md) |
[Gate matrix](test-matrix.md) |
[Historical G13B5](../history/e62-autonomous-functional-sitl.md) |
[Historical G13B7](../history/e62-g13b7-autonomous-stage-regression.md) |
[Historical G13B7.1](../history/e62-g13b7-1-correctness-review.md).
