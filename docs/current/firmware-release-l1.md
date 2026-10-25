# E62 L1 Firmware Release Regression — Operational Contract

**Goal:** a repeatable release-time **firmware functional** qualification
running the same checked-in original ESCape32 ELF in **one exact rebuilt
QEMU model**. This is not electrical qualification or rotor validation.

## Release operation

Workflow: [E62 L1 Firmware Release Functional Gate](../../.github/workflows/e62-firmware-release-l1.yml).

Run **Actions → E62 L1 Firmware Release Functional Gate → Run workflow**,
provide a unique `release_id`, the **tracked ELF** path, and the actual
64-character SHA256. The workflow also runs on release tags matching
`e62-fw-*`. Updating this workflow or its validator triggers a
one-time main-branch baseline audit.

A candidate with changed symbols/peripheral assumptions fails CLOSED.
The future released ELF must be committed with its own source/license/
build provenance before qualification; a filename alone is not proof.

## Independent gates, all mandatory

| Gate | Guest evidence | Boundary |
|---|---|---|
| T01 | 11s/11,000 real simulated wire packets, Ramp/Hold, timer associations, neutral teardown | Scripted BEMF only |
| T02 | 110s/110,000 packets, 11 Stage physical boundaries, 0–100% commands, sampled Guest throttle | Scripted BEMF only |
| DShot CRC | Separate valid/corrupt PA26 physical frames, original DMA/callback, `valid_frame_feeds` +1/0 | Not signal-loss recovery |
| nFAULT/OC-U/V/W | Physical model Trip, original IPSR=44 and source Shutdown, Gate inactive | Modeled neutral device/Guest |
| WWDT G5 | Original peripheral timer/feed behavior | Device model only |
| WWDT G14 | opt-in simulated 0x0E BOOTRST, PB13 LOW and frozen PWM | Not Guest loss-of-signal recovery |

The CI begins with a clean runner, builds QEMU once and verifies the
same ELF checksum, then executes every native gate with `set -euo
pipefail`. An independent aggregator
`tools/ci/firmware_release_l1.py` revalidates all raw JSON. Missing
evidence, incomplete stages, bad CRC, or unexpected shutdown fails
the release. JSON stores Git HEAD, QEMU submodule SHA, actual QEMU
executable SHA256, ELF path and SHA256, release ID, scenario hash,
gate results and explicit nonclaims.

**L1 PASS does not waive L2 known FAIL:** G13B3M rotor reversal and
uncalibrated Guest-coupled motor dynamics remain separate blockers for
motor/flight qualification. Actual ARM silicon reset, motor current,
propeller, EMC/EMI, protection thresholds and thermal behavior require
HIL/bench evidence.

## Local preparation and evidence

```bash
git pull --ff-only
python3 -m unittest discover -s tests -p 'test_firmware_release_l1.py' -v
bash tools/ci/check_autonomous_host.sh
```

To reproduce the full release suite, use the commands in the linked
GitHub Actions workflow on the same ELF and QEMU binary. Do not
mix JSON files from older commits or other QEMU builds when assembling
a release verdict.

## L2 parallel lane

[G14 original-QEMU clocked PWM → current-continuous BLDC → BEMF](../../.github/workflows/e62-g14-clocked-current.yml)
is a **strict independent Gate**. It must validate chronological
AQ/DB edges, Guest CAP1/TIMG12 commutation, direction and motor energy
without relaxing `G13B3M`. A model-only or Host PASS is not
a substitute for original Guest closed-loop PASS.
