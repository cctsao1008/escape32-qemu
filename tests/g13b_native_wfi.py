#!/usr/bin/env python3
"""G13B shared original-ELF WFI rendezvous.

The native firmware can contain multiple WFI opcodes in separate control
branches. An objdump address is a *candidate*, never proof of execution.
Set breakpoints on every original native-main WFI. Use bounded real TCG
execution with explicit fault/timeout evidence. Do NOT mock guest state,
supply guest registers, synthesize SysTick or skip arming checks.
"""
from g11_exception_lifecycle import observer, continue_bounded


def wait_for_native_main_wfi(rsp, wfi_pcs, hardfault, slice_ms,
                             max_slices=12, stage="NATIVE_MAIN"):
    """Return the *observed* WFI PC. Caller owns the installed breakpoints.

    A Ctrl-C bounded pause is NOT a successful WFI rendezvous. Continue
    only after checking CPU fault registers, and fail if all slices expire.
    """
    allowed = set(wfi_pcs)
    if not allowed or hardfault in allowed or max_slices < 1:
        raise ValueError("Bad original ELF WFI breakpoint configuration")
    for n in range(max_slices):
        stop, interrupted = continue_bounded(rsp, slice_ms)
        if not stop.startswith(("S02", "T02", "S05", "T05")):
            raise RuntimeError(f"{stage}: unexpected GDB stop: {stop!r}")
        state = observer(rsp)
        pc = state["pc"]
        if (pc == hardfault or state["cfsr"] or state["hfsr"] or
                state["ipsr"] == 3):
            raise AssertionError(
                f"{stage}: genuine native CPU fault "
                f"pc=0x{pc:08x} ipsr={state['ipsr']} "
                f"CFSR=0x{state['cfsr']:08x} "
                f"HFSR=0x{state['hfsr']:08x}")
        if interrupted:
            print(f"G13B_{stage}_BOUNDED_PAUSE "
                  f"slice={n + 1}/{max_slices} "
                  f"pc=0x{pc:08x} ipsr={state['ipsr']} "
                  f"primask={state['primask']} "
                  f"icsr=0x{state['icsr']:08x}", flush=True)
            continue
        if pc not in allowed:
            raise AssertionError(
                f"{stage}: stopped at non-WFI PC=0x{pc:08x}; "
                "a breakpoint was hit, not native WFI")
        if state["ipsr"] != 0 or state["primask"] != 0:
            raise AssertionError(
                f"{stage}: WFI not in unmasked native Thread mode "
                f"pc=0x{pc:08x} ipsr={state['ipsr']} "
                f"primask={state['primask']}")
        print(f"G13B_{stage}_OBSERVED_NATIVE_WFI "
              f"pc=0x{pc:08x} candidate_index={tuple(wfi_pcs).index(pc)} "
              f"slice={n + 1}/{max_slices} "
              "ORIGINAL_ELF_NOT_INFERRED_FROM_OBJDUMP", flush=True)
        return pc

    state = observer(rsp)
    raise AssertionError(
        f"{stage}: no real native main WFI in {max_slices} x "
        f"{slice_ms}ms bounded guest execution "
        f"(not a PASS); last_pc=0x{state['pc']:08x} "
        f"ipsr={state['ipsr']} primask={state['primask']} "
        f"icsr=0x{state['icsr']:08x} "
        f"CFSR=0x{state['cfsr']:08x} "
        f"HFSR=0x{state['hfsr']:08x}; "
        f"candidates={[hex(pc) for pc in wfi_pcs]}. "
        "Run G12 --require-wfi-roundtrip against this exact ELF.")
