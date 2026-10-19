# E62 / G1: MCPWM4 TBCTL precise BusFault

## Reproduction evidence (before AM13E HAL correction)

- QEMU: `cctsao1008/escape32-qemu`, commit `d79fbeaea57b95df065d874c579a8596670c1a30`.
- Firmware: `cctsao1008/ESCape32` `am13e-port-v2`, commit `0f21de6b8d5c011183094587294c04819fa67723`.
- ELF: `AM13E-rev17.3.elf`, captured from the real firmware CI artifact.
- G1: `CFSR=0x00008200` (precise bus error, BFAR valid), `BFAR=0x40014010`, stacked PC `0x0000d558`.
- ELF disassembly: `DL_MCPWM_setEmulationMode` stores to `[r0+0x10]` at `0x0000d558`.
- `MCPWM4_BASE=0x40014000`, so the destination is `MCPWM4.TBCTL`, not an unrelated MMIO access.

## Root cause and boundary

The native Firmware HAL called `DL_MCPWM_init(MCPWM4, ...)` without first enabling `SYSCTL.PWREN_MCPERIPH.PWM4` (bit 9). TI DriverLib's `DL_MCPWM_init` configures MCPWM registers; it does **not** acquire peripheral power on behalf of the caller.

The QEMU model intentionally rejects *writes* to an unpowered MCPWM4. Rejecting this invalid initialization order is correct; accepting arbitrary TBCTL writes would manufacture peripheral readiness.

Firmware change: `b0204670515d2de0b2480b52273038f1ee13d30a` on `am13e-port-v2`:

1. Keep MCPWM GPIO pads disconnected.
2. Call `DL_SYSCTL_enablePower(DL_SYSCTL_PWREN_PWM4)`.
3. Require `DL_SYSCTL_isPowerEnabled(DL_SYSCTL_PWREN_PWM4)`.
4. Freeze TBCLK, then call the original `DL_MCPWM_init` / MOTOR HAL transaction.

No change to original Rel17 ESCape32 commutation, duty, DShot, BEMF, or control algorithms. The patch is in the AM13E-specific HAL, not `src/main.c`.

## Regression evidence and non-goals

The emulator labels an unpowered write `G9_MCPWM4_POWER_OFF_WRITE` and returns a bus error. A test verifies that such a write is rejected rather than silently accepted.

G0/G1 obtain their application vector from the provided ELF, rather than assuming the previous reset PC; G1 resolves `DL_Common_delayCycles` through the ELF function symbol and still checks the loop opcodes before using a GDB continue-to-return that **executes** all actual guest instructions.

The GitHub workflow `.github/workflows/esc-sim-regression.yml` builds the original firmware Application ELF at pinned firmware and SDK commits, builds the pinned QEMU model, executes G0–G9 regression tests, and runs a bounded extended G1 trace with an explicit PWM4 native-initialization assertion. Consult the actual workflow result and logs before reporting a run as passing.

This finding proves a *startup MMIO access issue*. It does **not** independently prove physical PWM pad drive, valid DShot decode, live motor current/RPM/rotor angle/BEMF feedback, comparator capture, or a firmware/motor closed loop. G9 remains incomplete until all those links are backed by independently observed guest behavior.


## Executed integration result (2026-10-20, Taiwan time)

GitHub Actions: https://github.com/cctsao1008/escape32-qemu/actions/runs/39291391842 (run succeeded).

The workflow built the real Firmware Application ELF from the pinned `b020467` and TI SDK `b872469`, compiled the AM13E QEMU model, and ran the full existing peripheral-level suite.

- G0 through G8: regression checks PASS.
- G9a: isolated MCPWM4 output observer tests PASS (not motor/BEMF closed-loop).
- G1 native PWM4 power and TBCTL/TBPRD observation:
  - `PWREN=0x00000210`
  - `TBCTL=0x00040806`
  - `TBPRD=4165`
  - `PASS_G1_NATIVE_PWM4_HAL_INITIALIZATION_ONLY`
- Old fault `BFAR=0x40014010` is **eliminated**.
- G1 continues to a **new**, unmodeled feedback-path exception:
  - `reason=hardfault-vector`
  - `steps=15253` (host GDB observations, not instruction count)
  - `CFSR=0x00008200`, `BFAR=0x4044102A`
  - `stacked_PC=0x0000D13A`, `stacked_LR=0x0000B351`
  - `delay_continue_count=4`
  - On the freshly compiled ELF, this is a 16-bit `STRH` in `DL_ECAP_init()`, reached from the native BEMF initialization path.

**Result classification:** The specific G1 MCPWM4 power fault is fixed and its startup register state verified; G1 full firmware startup is **not** complete because ECAP1 BEMF capture is not yet modeled. ECAP1 must be modeled as an input, capture timer, status and IRQ signal chain, not as an arbitrary read/write MMIO pad. Comparator input must ultimately be driven by the host motor physics model through a real, explicit feedback interface. Do not report PWM motor closed-loop PASS on this evidence.
