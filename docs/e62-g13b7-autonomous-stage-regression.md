# E62 G13B7 — Coalesced Autonomous SITL / Temporal Evidence / Stage Gate

## Baseline and contract

Pinned **unaltered** ESCape32 Rel17.3 ELF:
SHA256 05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0.

G13B6 T01 is the *previous native reference* (not reproduced yet on G13B7):
11,000 DShot600 frames, 10,562 original valid CRC feeds, 10,068 original
CAP1 services/captures, 10,050 original TIMG12 services, 10,086
scripted BEMF transitions, 50,290 BEMF timer callbacks, 60,303
meaningful route change notifications, 44.34s **total wall time**,
36.54s autonomous-runtime wall time, PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL.

The G13B7 implementation is a **proposal until rebuilt custom QEMU**
and a full native T01 run show actual performance and functional parity.

## 1 — Earliest-deadline coalescing

G13B6 reissued timer_mod(now+100ns) on every changed route signature,
potentially pushing a pending earlier re-evaluation later. G13B7:
- preserves every actual changed comparator/ECAP/PWM route fingerprint;
- when a timer is pending at or before the desired now+100ns
  re-evaluation, **does not overwrite it**;
- when the pending timer is later, schedules now+100ns as before;
- retains the autonomous 750us virtual Zero Crossing events;
- adds route duplicate, coalesced deadline, and actual timer_mod counters.

This cannot promise fewer actual callbacks: the physical DShot600 input
still uses 32 PA26 edges per frame and Guest still runs normally.
No Guest RAM/peripheral/IRQ writes are introduced.

## 2 — BEMF/CAP1/TIMG12 timing evidence

QEMU records each actual scripted analogue voltage transition, each
routed CAP1 event **after** the ECAP acceptance logic, and each real
TIMG12 timer ZERO event with IRQ mask enabled **after** the IRQ update.
It does not manufacture an IRQ or modify Guest state.

Independent temporally adjacent pairs are matched within a fixed
3ms window (first unmatched crossing -> next CAP1 -> next TIMG12 ZERO).
Sample count, min/max/last/mean latency, unpaired events and overwrite
counts are exported in a SIM_ONLY 32-bit LE MMIO window. An adjacent
temporal pair does **not** prove Guest ISR entry, motor RPM, torque,
or that a particular crossing caused a later IRQ. Native Guest
'captured_events' and 'serviced' counter deltas remain separately
required for the aggregate functional oracle.

New port revision (0x5ffea000 + 0x88) is ABI **3**. ABI 2 builds must
fail closed; rebuild QEMU using ./build.sh. Additional registers:
0x8c meaningful changed routes, 0x90 coalesced early-deadline checks,
0x94 actual feedback timer_mods, 0x98 duplicate fingerprints;
0x9c actual CAP1 events, 0xa0 TIMG12 zero events with IRQ enabled,
0xa4 crossing/CAP1 pairs, 0xa8 CAP1/T12 pairs, 0xac full temporal
triplets. 0xb0..0xc4 last/max/min latency in ns;
0xc8..0xd4 64-bit sum ns; 0xd8..0xe4 unmatched/overwritten counters;
0xe8..0xfc final virtual-time event timestamps.

## 3 — Stage-sampled Functional Regression Gate

Separate from the existing full Scenario Aggregate Oracle, the
G13B7 *SAMPLED* gate checks:
- every full-duration physical stage latch complete, exact boundary;
- 3+ non-coherent Guest samples per stage;
- Rel17.3 original Guest internal throttle corresponds to expected
  positive DShot command minus 47 (neutral zero);
- 0->90% ramp progression and ±100 counts tolerance for asynchronous
  sample skew; positive flat HOLD ±2 counts and samples spanning >=50%
  of its duration;
- CRC feed counters monotonically increase between samples;
- positive-throttle stages show original CAP1 and TIMG12 monotonic
  progress and at least two acceptable modeled PWM duty snapshots;
- temporal trace includes CAP1 and TIMG12 events and >=1 temporally
  linked Crossing->CAP1->TIMG12 chain.

These are **sampled functional regression criteria**, not acceptance of
all 11,000 CRC frames, electrical safety/thermal evidence, or a
physical BLDC/FOC rotor model. G13B4 and G13B6 prior passes retain
their historical verdict wording and were not rewritten.

Neutral teardown remains source-owned through physical PA26 Zero
DShot and is attempted on a completed full-duration run even if the
new stage gate fails. A 50-frame bounded smoke is **always OPEN**,
never a full Functional PASS.

## Build and validate on WSL Ubuntu22.04

    cd ~/github/escape32-qemu
    git pull --ff-only
    ./build.sh
    python3 -m py_compile tools/autonomous_sitl_host.py \
      tools/autonomous_sitl_runner.py tests/g13b4_functional_dshot_sitl.py
    python3 -m unittest discover -s tests -p 'test_autonomous*.py' -v

50-frame smoke (expected OPEN_AUTONOMOUS_BOUNDED_SMOKE):

    python3 tests/g13b4_functional_dshot_sitl.py --autonomous \
      --qemu .build/qemu-src/build/qemu-system-arm \
      --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
      --cfg-flash artifacts/e62-g13b3-functional-cfg-flash.bin \
      --plan scenarios/e62-dshot-v1.json --id T01 --max-frames 50 \
      --artifact artifacts/e62-g13b7-t01-smoke.json

Full T01 (only after successful native smoke):

    set -o pipefail
    /usr/bin/time -p python3 tests/g13b4_functional_dshot_sitl.py \
      --autonomous --autonomous-telemetry-interval-ms 200 \
      --qemu .build/qemu-src/build/qemu-system-arm \
      --elf baseline/e62-g13b3/firmware/AM13E-rev17.3.elf \
      --cfg-flash artifacts/e62-g13b3-functional-cfg-flash.bin \
      --plan scenarios/e62-dshot-v1.json --id T01 \
      --artifact artifacts/e62-g13b7-t01-full.json \
      2>&1 | tee artifacts/e62-g13b7-t01-full.log

Compare: total wall time, CRC acceptance deltas, CAP1/TIMG12 deltas,
original Guest throttle and modeled PWM stage samples, timer_mod count,
coalescing count, last/min/mean/max observed analogue->CAP1->TIMG12
timing. Differences in event counts **do not** imply equivalent
rotor behavior. Run T02 only after T01 functionality and performance
have been independently assessed.
