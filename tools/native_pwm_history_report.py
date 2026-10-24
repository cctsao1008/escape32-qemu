#!/usr/bin/env python3
"""Offline provenance checker for Guest WFI incremental QEMU PWM history.

Cannot certify physical gate/MOSFET/freewheel events or the original
strict rotor gate. Reports an explicit OPEN when WFI-cadence loss occurs.
"""
import argparse
import json
from pathlib import Path


def audit_native_pwm_history_trace(document, *, require_observed=False):
    meta=document.get("metadata") or {}
    history=document.get("pwm_history") or {}
    attach=history.get("attach")
    events=history.get("events")
    polls=history.get("wfi_polls")
    if (document.get("format")!="e62.sitl.native-wfi.v1" or
            not meta.get("host_guest_register_writes") is False or
            not meta.get("qemu_internal_history_opt_in") is True or
            not isinstance(meta.get("elf_sha256"),str) or
            len(meta["elf_sha256"])!=64 or
            history.get("scope")!=
                "ORIGINAL_GUEST_WFI_INCREMENTAL_QEMU_INTERNAL_PWM_HISTORY" or
            not isinstance(attach,dict) or
            not isinstance(events,list) or not isinstance(polls,list)):
        raise ValueError("Missing pinned original Guest/read-only WFI provenance")
    from_seq=attach.get("first_in_scope_sequence")
    if (not isinstance(from_seq,int) or from_seq<0 or
            history.get("stored_events")!=len(events) or
            history.get("observed_wfi_count")!=len(polls)):
        raise ValueError("Native PWM collector scope/size inconsistent")
    for i,event in enumerate(events):
        if (not isinstance(event.get("sequence"),int) or
                not isinstance(event.get("virtual_ns"),int) or
                not isinstance(event.get("observed_at_native_wfi"),int) or
                not isinstance(event.get("observed_wfi_ecap_elapsed_ns"),int)):
            raise ValueError("Malformed original Guest historical event")
        if i and (
                event["sequence"]<=events[i-1]["sequence"] or
                event["virtual_ns"]<events[i-1]["virtual_ns"] or
                event["observed_at_native_wfi"] <
                events[i-1]["observed_at_native_wfi"]):
            raise ValueError("QEMU event chronology regressed")
    missing=history.get("in_scope_missing_events")
    gaps=history.get("gaps")
    if (not isinstance(missing,int) or missing<0 or
            not isinstance(gaps,list) or
            sum(x["missing_events"] for x in gaps)!=missing):
        raise ValueError("Ring event loss was not fully accounted for")
    complete=bool(history.get("complete_since_gate_return"))
    if complete and (
            missing or history.get("collector_halted") or
            history.get("collection_errors") or
            history.get("qemu_invalid_model_events_since_attach") or
            not polls):
        raise ValueError("Incomplete PWM history spuriously marked complete")
    for claim in (
        "complete_since_qemu_pwm_reset",
        "full_past_carrier_edges_reconstructed",
        "qemu_virtual_ns_and_guest_ecap_ns_aligned",
        "physical_mosfet_edges_qualified",
        "actual_gate_driver_deadtime_qualified",
        "current_continuous_motor_plant_input_qualified",
        "motor_stability_qualified",
        "original_native_strict_rotor_gate_executed_here",
    ):
        if history.get(claim) is not False:
            raise ValueError("Unqualified physical/native claim: "+claim)
    edges=sum(x.get("kind")=="QEMU_CLOCKED_AQ_DB_EDGE" for x in events)
    zeros=sum(x.get("kind")=="QEMU_ORIGINAL_PWM_ZERO_CALLBACK" for x in events)
    if require_observed and (not polls or not edges or not zeros):
        raise ValueError("Actual original Guest WFI edge/ZERO callbacks missing")
    return {
        "scope":"SIM_ONLY_ORIGINAL_GUEST_WFI_QEMU_INTERNAL_EDGE_AUDIT",
        "elf_sha256":meta["elf_sha256"],
        "original_guest_wfi_polls":len(polls),
        "historical_events_saved":len(events),
        "qemu_virtual_clock_edge_callbacks":edges,
        "qemu_original_zero_callbacks":zeros,
        "pre_attach_history_unavailable":attach[
            "pre_attach_history_not_collected"],
        "pre_attach_qemu_ring_dropped":attach[
            "pre_attach_ring_dropped"],
        "in_scope_missing_events":missing,
        "collector_errors":history.get("collection_errors"),
        "history_complete_since_gate_return":complete,
        "trace_capture_state":document.get("capture_state"),
        "original_extended_strict_gate_not_checked_here":True,
        "current_continuous_plant_input_qualified":False,
        "physical_mosfet_switching_qualified":False,
        "native_rotor_stability_qualified":False,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--trace",type=Path,required=True)
    p.add_argument("--output",type=Path)
    p.add_argument("--require-observed-original-guest-edge",action="store_true")
    a=p.parse_args()
    report=audit_native_pwm_history_trace(
        json.loads(a.trace.read_text()),
        require_observed=a.require_observed_original_guest_edge)
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("G13B3_NATIVE_WFI_INCREMENTAL_PWM_HISTORY_EVIDENCE "+
          json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()
