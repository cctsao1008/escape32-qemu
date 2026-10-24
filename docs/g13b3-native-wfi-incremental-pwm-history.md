# E62 G13B3 — Original Guest WFI Incremental Historical PWM Collection

## What this stage does

New optional evidence path:

    Pinned original ESCape32 Rel17.3 ELF
      -> Guest-owned native PWM / ZERO / Shadow / Trip / raw PB13
      -> QEMU-clocked historical ring at 0x5FFE7000 (128 entries)
      -> read-only incremental host collector at each original Guest WFI
      -> preexisting SITL trace JSON, separate pwm_history section
      -> offline consistency report

No original Guest source/binary changes, no Guest SRAM/PWM/IRQ/CAP1
writes, no QEMU virtual clock steps added, no Motor Plant/analog change,
no rotor acceptance gate change. QTest reads are performed only when
explicit opt-in is enabled. The reader is host-only and does not issue
a write command or own the RSP/QTest sockets.

The original NativeWFI Trace Recorder and its ECAP/motor samples stay
unchanged. Existing numerical-frozen PWM convergence comparisons
remain available using that original exact same samples structure.

## Attaching to the original Guest

At the real observed native Gate-return WFI, the collector reads the
QEMU ring header twice to establish a stable baseline:

- actual cumulative QEMU event sequence;
- QEMU prior ring overflow count;
- QEMU prior invalid AQ/DB model count;
- latest QEMU event timestamp and internal six-output mask;
- original PWM ZERO event counter.

**Historical events that happened before Gate return are not fabricated.**
If QEMU had already overwritten events during startup, those appear as
pre_attach_ring_dropped. That number is not interpreted as a loss AFTER
the collector attached.

At each subsequent original Guest WFI checkpoint, the host reads the
QEMU header, calculates the unread sequence range, reads only newly
retained events (at most 128), then double-reads the header. The pause
is a genuine Guest-owned WFI breakpoint, not a QTest-generated PWM
peripheral stimulus. Each retained event records both:

- its original QEMU virtual event timestamp (nanoseconds);
- the original Guest WFI number / elapsed original ECAP1 time when
  the event was READ.

**These two clock epochs are NOT equated or aligned.** Original
ECAP1 relative Gate-return timestamps are NOT actual physical MOSFET
switching-edge timestamps.

The event mask and timestamp/zero counters are validated for order
and continuity, including the last observed mask at Guest Gate return.
Every admitted record retains the original monotonically increasing
QEMU sequence number. A skipped sequence is an explicit gap, NEVER a
fabricated completed event. A ring overflow is a real in-scope loss
only if some unread sequence was overwritten after the prior poll.
The QEMU cumulative dropped counter continues to be recorded but is
not by itself sufficient to prove an in-scope gap.

QEMU model-invalid history, a ring reset, inconsistent header,
unsupported record, WFI/ECAP regression, over-capacity host memory or
socket read error all halt only THIS auxiliary collector and leave an
unqualified partial evidence block. The original motor, BEMF,
strict rotor acceptance and firmware continue unchanged.

Original analog frontend failure (previously WFI 774) likewise still
persists the last successfully collected historical events and their
WFI links in the partial SITL trace.

## Trace format, qualification and limits

Opt-in creates a new root JSON key pwm_history, containing:
- attach (baseline, pre-attach events known to be unavailable);
- events (saved raw QEMU internal virtual-edge & register events);
- wfi_polls (number read / missing / cumulative QEMU counters);
- gaps (first/last unavailable QEMU event sequence);
- collection_errors (fail-closed reason at original WFI);
- complete_since_gate_return (TRUE only for observed valid uninterrupted
  in-scope sequence since attaching and with no errors);
- complete_since_qemu_pwm_reset = FALSE;
- current_continuous_motor_plant_input_qualified = FALSE;
- physical_mosfet_edges_qualified = FALSE;
- motor_stability_qualified = FALSE.

Historical records stop at 100,000 saved QEMU internal events by
default; the host does not trim a valid prefix to appear complete.

Because a WFI gap can contain more than 128 QEMU events, completeness
MUST be validated by actual sequence continuity. The observed PWM
frequency, number of WFI or carrier-plan edge count cannot replace
that check. If loss occurs, earlier valid records remain in the trace
but no full uninterrupted switching history is claimed.

This phase does not map QEMU INTERNAL AQ/DB logic levels through a
real gate-driver model. It cannot validate diode freewheel current,
deadtime and pin propagation. It does not yet drive the isolated
CurrentContinuousBLDC with a frozen original Guest historical waveform.

## Run host-only tests

    cd ~/github/escape32-qemu
    git pull --ff-only
    python3 tests/test_native_pwm_history_collector.py

## Original Guest test (separate from QTest synthetic device fixture)

Build the unchanged pinned QEMU and use the already pinned original
fast-ramp ELF. Generate original Guest factory Cfg via existing
pre-boot factory Flash fixture. Do NOT touch Guest SRAM.

    cd ~/github/escape32-qemu
    ./build.sh
    python3 tools/native_sim_cfg_flash.py \
      --sim-only-opt-in \
      --elf .build/e62-fw-fast-ramp/AM13E-rev17.3.elf \
      --output artifacts/g13b3n-original-cfg-flash.bin

    python3 tests/g13b2_native_drive_probe.py \
      --qemu .build/qemu-src/build/qemu-system-arm \
      --elf .build/e62-fw-fast-ramp/AM13E-rev17.3.elf \
      --throttle 1500 --startup-steps 32768 \
      --slice-ms 300 --runtime-slices 20 \
      --wait-native-bemf-calibration --calibration-wfi-visits 24 \
      --require-drive --require-native-pwm \
      --require-native-bemf-arm --require-native-sustained-loop \
      --sim-only-cfg-flash artifacts/g13b3n-original-cfg-flash.bin \
      --sustained-wfi-visits 2800 --sustained-sectors 12 \
      --sustained-min-integrated-ns 90000000 \
      --initial-electrical-degrees -30 \
      --sitl-native-pwm-history \
      --sitl-trace-output artifacts/g13b3m-native-sitl-trace.json \
      --artifact artifacts/g13b3m-extended-twelve-sector.json

    python3 tools/native_pwm_history_report.py \
      --trace artifacts/g13b3m-native-sitl-trace.json \
      --require-observed-original-guest-edge \
      --output artifacts/g13b3m-native-pwm-history-evidence.json

The original Guest test may still fail the unchanged rotor stability
gate; that is NOT a reason to change, skip or re-label it. The partial
SITL trace should still preserve history to the last successful WFI,
and the offline audit reports internal edge/ZERO callback evidence
separately. This feature cannot convert any original strict motor FAIL
to PASS.

## Distinguish three layers of evidence

1. ACTIVE register carrier plan — purely model-reconstructed CURRENT
   one-carrier output sequence. No past callbacks.
2. Historical QEMU event ring + Native WFI incremental collection —
   QEMU virtual-time executed internal AQ/DB changes correlated to
   genuine original Guest WFI stops. Can be complete ONLY over an
   observed bounded interval with no unread event loss.
3. Actual hardware MOSFET switching, deadtime, diode/freewheel and
   current continuity — still UNQUALIFIED / NOT MEASURED.

The next independent engineering task after this is WFI interval
waveform coverage analysis and well-grounded physical switch mapping.
No diode current or CurrentContinuousBLDC native feedback can be
inferred from QEMU internal history alone.
