# Source VBUS integration, v4

Experimental companion to firmware `diag/e62-dynamic-handover-evidence`, stacked on PR9. Full evidence and independent acceptance matrix: [v4 engineering report](https://github.com/cctsao1008/escape32-qemu/blob/report/e62-engineering-execution/docs/current/e62-engineering-status-v4.md).

The source-owned `E62_SIM_VBUS_V1` plan declares frame, input millivolts and sensor condition. It requires native motor/native ADC and forbids a competing ADC fixture. Frame0 is24V; changes are bounded18–26V. Sensor0 is connected,1 opens the sense input (native raw0),2 stops the ADC1 conversion clock until reset. These are explicitly opt-in SIM_ONLY inputs; the motor constants/integration equations and default24V path remain unchanged. The affine phase network is declared virtual, not measured calibration.

`tools/e62_run_vbus_campaign.py` checks explicit QEMU/ELF SHA256 pins before launching and records exact commands and all input hashes. Constant, up/down, invalid and stale cases use versioned scenarios in `scenarios/e62-v4`. Offline `tools/e62_vbus_handover_audit.py` verifies sample identity, Guest reads, independent calibrated conversion, phase/polarity, source load timing, same epoch, actual active code, quarantine and fresh ready observations. Missing evidence remains incomplete. `tools/e62_startup_reference_audit.py` keeps raw CAP1, actual firmware decisions and sampled rotor state distinct.

Executed validation:37 focused tests,11 paused-start plan checks, native sample/DAC chains for23V and24.5V, invalid/stale shutdowns and a SHA-guarded up/down campaign replay. Firmware companion107 full SDK regression groups pass. Both real handovers have2ZERO events before the software-ready observation. Two ZERO periods are a synthetic policy, not measured analog settling. Invalid-input shutdown also has an expired prior sample; invalid-only-before-expiry is unisolated. Wrong-phase/epoch/delay coverage from register/offline tests remains labeled separately.

The first word-reader probes failed on live-ring snapshots and remain preserved. The bulk reader retains only identical committed records across two unhalted SRAM copies and exposes gaps. No BEMF/CAP/IRQ/rotor data is invented.

Startup remains failed: direct firmware history rejects2782us under the unchanged5000us startup window, then accepts13728us with2733us delay. Actual rotor reversal precedes commutation while fresh matched reference observations bracket it. More captures are not rotor synchronization. Flying restart is not exercised by the new short scenario. The saved344/492/532ns clock failures remain open despite47 completed follow-ups without recurrence.

Build experimental branches in isolated generated QEMU worktrees; the inherited timer observer intentionally patches ignored util/qemu-timer.c. Preserve executable hashes and failed evidence. No production merge, threshold waiver, hardware approval or issue closure is authorized by these results.
