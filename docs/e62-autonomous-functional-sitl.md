# E62 G13B5 — Autonomous Functional SITL (experimental)

## Motivation and scope

T01 legacy functional SIM_ONLY completed 11.000125 seconds of original
Rel17.3 guest time and reported **PASS_FUNCTIONAL_SCRIPTED_BEMF_ONLY**:
11,000 physical DShot sends, 9,757 valid Guest CRC feed deltas,
9,310 CAP1 captures, and 9,296 TIMG12 services, but required **202,059
GDB/WFI rendezvous**. This is the regression reference, not a physical
motor/rotor qualification.

G13B5 is a new opt-in execution strategy:
- 1 kHz DShot600 is scheduled by **QEMU virtual time**, every actual
  frame is rendered into **32 external PA26 line edges**, and existing
  TIMG4 CC0/DMA/unchanged Guest decoder decides whether it receives it.
- **G13B6 event-driven BEMF**: native Guest writes that actually change
  CMPSS MUX/polarity, DAC, ECAP configuration or PWM power/clock
  schedule a deferred analogue re-evaluation. The next idealized
  half-cycle crossing is scheduled as a single **750us one-shot QEMU
  Virtual Clock** event. While the route is disabled, the generator
  sleeps until a relevant Guest MMIO change; no fixed 100us polling.
  This is functional analogue stimulus, not rotor physics.
- The original Firmware is not rebuilt, edited, or instrumented; there
  are **no writes** to Guest RAM, native PWM, CAP1, TIMG12, IRQ, or
  exception registers.
- Python preserves the physical-zero arming/CRC/startup proof but does
  not set any per-WFI breakpoint during the autonomous runtime.
- A new read-only **stage-end latch** records simulator PA26 captures,
  DMA beats, scripted BEMF crossings and callback counts at precise
  scenario virtual-time boundaries.
- Low-rate QTest diagnostic telemetry (default 200ms of **Guest Virtual
  Time**) samples Guest throttle, valid-CRC feed counters, CAP1/TIMG12
  and modeled six-channel PWM high ticks. These samples while running
  are **not coherent snapshots**; staged Guest values are labelled
  asynchronous diagnostics, not per-stage firmware acceptance proof.
  Original source totals are checked again after the Guest is halted.

**Acceptance distinction:** Legacy G13B4 still uses per-stage guest
evidence. The new G13B5 full pass label is
`PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL`; it means all physical stimulus
frames were scheduled and Guest aggregate CRC/CAP1/TIMG12 counters
progressed, *not* that every input frame was CRC-accepted or each stage
passed its own exact throttle/duty response gate. Stage-specific
Guest acceptance and silicon/rotor/energy physics remain OPEN.

## Build and run (Ubuntu 22.04 source QEMU)

```bash
cd ~/github/escape32-qemu
git pull --ff-only
./build.sh

python3 -m unittest discover -s tests -p 'test_autonomous*.py' -v

# Retain your verified factory Cfg image from the original pinned ELF.
python3 tests/g13b4_functional_dshot_sitl.py \
  --autonomous \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-functional-cfg-flash.bin \
  --plan scenarios/e62-dshot-v1.json --id T01 \
  --max-frames 50 \
  --artifact artifacts/e62-autonomous-t01-smoke.json
```

Bounded smoke is intentionally `OPEN_AUTONOMOUS_BOUNDED_SMOKE`
(exit status nonzero), never a qualified full PASS. Only after it has
run on your rebuilt custom QEMU may you remove `--max-frames 50`
for complete T01; T02 follows, not precedes, T01 confirmation.

For the next 11-second T01 A/B regression:
```bash
/usr/bin/time -p python3 tests/g13b4_functional_dshot_sitl.py \
  --autonomous --autonomous-telemetry-interval-ms 200 \
  --qemu .build/qemu-src/build/qemu-system-arm \
  --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
  --cfg-flash artifacts/e62-g13b3-functional-cfg-flash.bin \
  --plan scenarios/e62-dshot-v1.json --id T01 \
  --artifact artifacts/e62-autonomous-t01-g13b6-full.json
```

The previous G13B5 T01 full reference observed **48.76s total wall time**
and **11s Guest time**, **11,000 DShot sends**, **10,564 valid CRC
feed delta**, **9,099 CAP1** and **9,083 TIMG12 services**. These are
*previous-run observations*, not G13B6 expectations or minimums.
Use `/usr/bin/time` to measure the actual new result.

The legacy proven path is unchanged; omit `--autonomous` to run it.
The new engine is not present in pinned historical QEMU binaries, so
use `.build/qemu-src/build/qemu-system-arm`, not the older pinned executable.

## Test-only MMIO 0x5ffea000 (G13B5)

The non-silicon test port exists only with `esc-sim=on`.
Stage programming is 32-bit LE:
`+00` magic `0x41323645`; `+04` 1 START / 2 ABORT / 3 RESET;
`+08` running=1/done=2/error=4; `+0c` stage count (max16);
`+10` stage select; `+14` duration ms;
`+18` from-permille; `+1c` to-permille;
`+20` update ms; `+24` max frames (0 full).
Read-only: `+28` sent, `+2c` expected, `+30` last DShot,
`+34` scripted analogue transitions, `+38` elapsed ms,
`+3c` error, `+40/44` elapsed ns, `+48` analogue writes,
`+4c` powered-event observations, `+50` current stage,
`+54/58` PA26 physical capture/DMA totals.

G13B6 ABI v2 adds: `+5c` stage evidence index (test-only bank select);
`+60` cumulative DShot frames at stage end; `+64` cumulative PA26
captures; `+68` cumulative DMA beats; `+6c` scripted BEMF transition
count; `+70` stage valid/completed flags; `+74` stage-end virtual ms;
`+78` cumulative BEMF timer callbacks; `+7c` analogue writes;
`+80` live BEMF callbacks; `+84` live route reschedules;
`+88` ABI version = **2**.

The test Host rejects the older ABI rather than silently pretending
stage evidence is available. QEMU latched counters are simulator-side
physical stimulus observations only, **not Guest stage CRC/PWM proof**.
Each frame is due every 1ms of QEMU virtual time. The DShot scheme,
0% neutral, 48..2047 positive value and half-even rounding match
`tools/functional_dshot_scenario.py`.

## Engineering cautions

This is a **source-code integration proposal until the local rebuilt
QEMU and native Guest smoke test execute**. Do not claim speed
improvement, CI regression success or native emulator pass based on
unit tests alone. Measure real wall time for T01 in both modes.
The idealized 750us half-cycle crossing and deferred response to Guest
route writes are test-fixture approximations, not production BEMF physics.
The event-driven code has not yet been compiled and exercised in the
user's custom QEMU. Even a full aggregate pass does not alter the
separately failing G13B3M rotor-stability/energy gate.
