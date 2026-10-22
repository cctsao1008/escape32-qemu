# E62 — G13B3M endurance and physical-lab evidence bridge

## Scope, immutable passing reference, and honesty boundary

- **Original passing baseline:** `escape32-qemu/main@17b0153ccadcf8578fdb6092b26b03e8a3a4d2a1`, Full CI **#39839423474**, Host CI **#39839423430**, original G13B3L native 6/6 powered feedback sectors. Keep the commit reachable and preserve its original six-sector CI step unmodified.
- **Added, independent G13B3M:** same pinned ESCape32 Rel17.3 source + QEMU, opt-in `g13b3l_sim_only_ramp.cmake` and factory Cfg Flash. Strictly test **12 original accepted CAP1→TIMG12→native powered PWM sector transitions** over **two complete 1→2→3→4→5→6→1 rotations**; require 90 ms of ECAP-timed model integration and 600 native powered PWM observations. This is a step above the six-sector baseline, not a replacement.
- QEMU's ideal floating-star motor uses a **24 V** virtual DC bus, **0.3 Ω per phase**, **2 mH per phase**, **7 pole pairs**. These are synthetic test parameters, not the Queen Bee motor. The customer motor data has **21 pole pairs**, 0.0566 Ω *phase-to-phase* resistance, and 0.0175 mH *phase-to-phase* inductance. **Do not scale** the simulated model's RPM/current/energy into 47 V hardware performance.
- The E62 MCU/power-stage option (Si/DRV8300N or proposed GaN) does not imply a finished PCB, measured duty, current sense path, protection speed or MOSFET junction temperature. Every physical test remains **OPEN** until an instrument trace + identifiable DUT + engineering review exists.

## Physical conditions and escalation

| ID | Condition | Purpose | Status |
|---|---|---|---|
| H0 | Board unpowered; confirm pin mapping, power domains, wiring, phase labels, probe grounds, gate-driver and measurement limits | Prevent connecting an unqualified high-energy bridge to the rotor | OPEN |
| H1 | Current-limited, low-energy commissioning; guarded/no-prop arrangement | Six gate outputs, carrier, complementary dead-time, three fault paths and gate-off latency | OPEN |
| H2 | **47 V**, maxon EC 87 flat UAV 210 KV + **APC 24×12E**, controlled hover thrust rig and propeller airflow | 45 N continuous hover without thermal derating; motor vs DC input current; MOSFET/ECAP/driver hot spots; efficiency versus reference | OPEN |
| H3 | From H2 normal hover temperature; controlled **5 s** peak repetitions, duty cycle/interval **TBD** | ≥90 N thrust, motor-side 80 A capability, repeated thermal and electrical protection margin | OPEN |
| H4 | CW and CCW with direction handling explicitly defined | Direction operation and re-arming/reversal safety | OPEN |

**The 50 A continuous / 80 A peak requirements concern motor-side current**, *not* battery/47 V DC-bus current. The baseline does not define RMS vs peak vs d/q controller magnitude, so instrumentation/algorithm equivalence and acceptance must be resolved before current PASS. Continuous test thermal equilibrium/derating criteria and repetition duty cycle are also currently unspecified. Do not invent thresholds. Use rated isolated probes and a mechanically protected thrust rig; do not run an exposed 24-inch propeller during low-energy bring-up.

## Four-domain evidence matrix

All metric IDs and units are machine-checked by `tools/e62_hardware_evidence.py` against `docs/fixtures/e62-hardware-measurements.csv`. Hardware values are deliberately **blank**. The data may be populated only after an actual bench run, with a board serial/revision, *actual tested firmware SHA*, instrument ID, UTC time and retained raw waveform/thermal file reference.

| Domain | Hardware trace and quantity | Native SIM_ONLY counterpart | Review boundary |
|---|---|---|---|
| **PWM** | Six-phase gate and switch-node captures, carrier Hz, high/low deadtime ns, overlap, Vgs, Vds overshoot. Capture a complete six-step period and actual Gate/Trip assertion state. | Original `sector_evidence[].pwm_before/after`, native `step`, `selected_code`, source/return pairs, exact original Rel17 sequence; MCPWM model **not silicon timing calibrated** | Compare **logical order and ownership only**. Do not infer actual Vgs, switching overshoot, deadtime or shoot-through margin from QEMU. |
| **CURRENT** | Three phase currents with probe type and stated RMS/peak definition; DC-bus current independently; input power W. Capture steady hover and 5-s peak transient. | Simplified 24 V two-terminal R-L model power/work and simulated RPM; **NOT the 47 V 21-pole-pair hardware** | No numerical current/efficiency equivalence. Customer ~50 A continuous and 80 A / 5 s are motor-side requirements; confirm measurement basis. |
| **PROTECTION** | Native nFAULT and each phase OC assertion; six PWM/gate-off times, hardware state latched, command/watchdog/rearm handling | QEMU G13B2D, G13B2E post-Gate fault, G13B3H prove simulated Trip/ISR ordering; G13B3M nominal run checks no OST2/OST3 at gate | Verify functional correspondence; numeric trip propagation and final safe state **require scope traces**. No supplied numeric latency limit; EE/customer approval needed. |
| **THERMAL** | MOSFET hotspot, electrolytic capacitor hotspot, gate-driver hotspot, ambient temperature, equilibrium test duration; warm-start peak traces | **NOT MODELED**; QEMU model energy is not board heat | 47 V hover ≥45 N must avoid thermal derating. For peak, 90 N/5 s from warmed condition; define repeated-cycle interval and component ratings first. |

## Capture/review workflow

1. Preserve G13B3L 6/6, the G13B3M extended report and the exact commit/ELF/config SHA. A model-only unit test **never** substitutes for firmware-backed QEMU native evidence.
2. Perform H0/H1 first; lock instrument settings and raw waveform names, firmware SHA, board/phase mapping, Gate polarity, and calibration; verify fault *before* power loading.
3. H2/H3/H4 only in approved guarded setups, with measured **DC bus 47 V**, actual prop cooling, thrust, motor current definition and thermal traces. Compare with the same reference ESC/motor/prop conditions for efficiency.
4. Fill the CSV one metric per row. `OPEN` rows must have **no value**; `CAPTURED` rows require direct hardware provenance. `PASS` cannot be entered into the CSV automatically, and even complete capture stays awaiting independent review.
5. Store raw files and attach a signed physical test report with acceptance rules, component derating and any deviations. Model and hardware files must not share a fabricated pass label.

```bash
python3 tools/e62_hardware_evidence.py \
  --csv docs/fixtures/e62-hardware-measurements.csv \
  --output artifacts/e62-hardware-evidence-intake.json
# PASS_E62_HARDWARE_EVIDENCE_SCHEMA_VALIDATION_ONLY
# Hardware qualification remains OPEN_NOT_MEASURED until lab capture/review.
```

**Customer baseline:** supplied `Queen_Bee_Customer_Requirements_Baseline.md`, §2.1–2.5 and §4. Physical power-stage options are only *architecture candidates* per supplied `Next_Gen_ESC_Architecture_Cost_Reference.md`, not proof of an implemented E62 board.
