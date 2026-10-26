#!/usr/bin/env python3
"""Offline original-Guest DMA0/IRQ/CPU triage for E62 no-WFI artifact.

Read the EXISTING no-WFI JSON. Do not run QEMU, change Guest registers,
infer an ISR merely from a pending raw DMA bit, or alter strict gates.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ORIGINAL_SHA = "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"


def diagnose(artifact):
    stage_records = artifact.get("runtime_diagnostics_by_stage") or []
    last_stage = next((s for s in reversed(stage_records)
                       if isinstance(s, dict) and s.get("receiver_and_cpu")), None)
    receiver = (artifact.get("receiver_after")
                or artifact.get("receiver_at_failure")
                or (last_stage or {}).get("receiver_and_cpu"))
    guest = (artifact.get("original_guest_after")
             or artifact.get("original_guest_at_failure")
             or (last_stage or {}).get("original_guest")
             or {})
    auto = artifact.get("autonomous_dshot") or artifact.get("last_successful_dshot_poll") or {}
    out = {
        "classification":"NO_TERMINAL_CPU_IRQ_SNAPSHOT",
        "source_snapshot":(
            "receiver_after" if artifact.get("receiver_after") else
            "receiver_at_failure" if artifact.get("receiver_at_failure") else
            "last_stage" if receiver else "absent"),
        "dshot_sent":auto.get("sent"),
        "dshot_status":auto.get("status"),
        "guest_valid_frame_feeds":guest.get("valid_frame_feeds"),
        "warnings":[],
    }
    if not receiver:
        out["warnings"].append("NO_CPU_CONTEXT_IN_EXISTING_ARTIFACT")
        return out
    irq_raw = int(receiver.get("dma_irq_raw",0))
    irq_mask = int(receiver.get("dma_irq_mask",0))
    irq_masked = int(receiver.get("dma_irq_masked",0))
    ipsr = receiver.get("cpu_exception_ipsr")
    primask = receiver.get("cpu_primask")
    nvic_irq = ipsr-16 if isinstance(ipsr,int) and ipsr >= 16 else None
    flags={
        "ch2_full_completion":bool(irq_raw & (1<<2)),
        "ch2_half_completion":bool(irq_raw & (1<<18)),
        "dma_address_error":bool(irq_raw & (1<<24)),
    }
    out.update({
        "guest_cpu_pc":receiver.get("cpu_pc"),
        "guest_cpu_pc_hex":(
            hex(receiver["cpu_pc"]) if isinstance(receiver.get("cpu_pc"),int)
            else None),
        "guest_cpu_lr_hex":(
            hex(receiver["cpu_lr"]) if isinstance(receiver.get("cpu_lr"),int)
            else None),
        "guest_cpu_ipsr":ipsr,
        "guest_cpu_primask":primask,
        "nvic_active_external_irq":nvic_irq,
        "dma_ch2_remaining":receiver.get("dma_ch2_remaining"),
        "dma_ch2_control_hex":hex(receiver.get("dma_ch2_control",0)),
        "dma_ch2_trigger":receiver.get("dma_ch2_trigger"),
        "dma_irq_raw_hex":hex(irq_raw),
        "dma_irq_mask_hex":hex(irq_mask),
        "dma_irq_masked_hex":hex(irq_masked),
        "dma_raw_flags":flags,
        "native_oc_codes":receiver.get("native_oc_adc_codes"),
        "native_power_trip_latched":receiver.get("native_ost_latched"),
    })
    reasons=[]
    if isinstance(ipsr,int) and ipsr in (3,4,5,6):
        reasons.append("CPU_IN_FAULT_EXCEPTION")
    if primask == 1:
        reasons.append("CPU_GLOBAL_INTERRUPTS_MASKED_AT_SNAPSHOT")
    if nvic_irq == 40:
        reasons.append("CPU_CURRENTLY_IN_DMA0_IRQ_AT_SNAPSHOT")
    elif isinstance(ipsr,int) and ipsr not in (0,3,4,5,6):
        reasons.append("CPU_IN_OTHER_EXCEPTION_AT_SNAPSHOT")
    if flags["dma_address_error"]:
        reasons.append("DMA_CH2_ADDRESS_ERROR_RAW_SET")
    if irq_masked:
        reasons.append("DMA_INTERRUPT_SOURCE_PENDING_AND_UNACKNOWLEDGED")
    if receiver.get("dma_ch2_remaining")==0:
        reasons.append("DMA_CH2_RX_BUFFER_EXHAUSTED")
    if receiver.get("native_ost_latched"):
        reasons.append("MOTOR_POWER_TRIP_LATCHED_INDEPENDENT_OF_DMA")
    if not reasons:
        reasons.append("INSUFFICIENT_EVIDENCE_FOR_DMA_OR_CPU_FAILURE")
    out["observations"]=reasons
    out["classification"]=(
        "CPU_FAULT_OBSERVED" if "CPU_IN_FAULT_EXCEPTION" in reasons else
        "CPU_INTERRUPTS_MASKED" if "CPU_GLOBAL_INTERRUPTS_MASKED_AT_SNAPSHOT" in reasons else
        "DMA0_ISR_ACTIVE" if "CPU_CURRENTLY_IN_DMA0_IRQ_AT_SNAPSHOT" in reasons else
        "DMA_PENDING_DELIVERY_UNRESOLVED" if irq_masked else
        "DMA_RX_STATE_UNRESOLVED")
    out["warnings"].extend([
        "PENDING_DMA_IRQ_DOES_NOT_PROVE_MISSING_NVIC_DELIVERY",
        "QTEST_READS_ARE_NON_ATOMIC_NO_GUEST_CPU_STOP",
        "SAMPLE_MAY_BE_AFTER_DMA_ACTIVITY_AND_FAULT",
        "MOTOR_TRIP_DOES_NOT_ESTABLISH_DSHOT_INGRESS_CAUSALITY",
    ])
    return out


def symbolize(result, elf):
    if elf is None or result.get("guest_cpu_pc") is None:
        return
    if hashlib.sha256(elf.read_bytes()).hexdigest()!=ORIGINAL_SHA:
        raise ValueError("Original Rel17.3 ELF SHA mismatch")
    pc=result["guest_cpu_pc"]
    if not isinstance(pc,int) or not 0x6000<=pc<=0x100000:
        result["original_elf_pc_symbol"]="PC_OUTSIDE_PINNED_GUEST_APP_FLASH"
        return
    out=subprocess.run(["arm-none-eabi-addr2line","-e",str(elf),
                        "-f","-C",f"0x{pc & ~1:x}"],
                       text=True,capture_output=True,check=True,timeout=10)
    result["original_elf_pc_symbol"]=out.stdout.strip().replace("\n"," | ")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifact",type=Path,required=True)
    p.add_argument("--elf",type=Path)
    a=p.parse_args()
    d=json.loads(a.artifact.read_text())
    out=diagnose(d)
    symbolize(out,a.elf)
    print("E62_NATIVE_DSHOT_OFFLINE_DMA_IRQ_CPU_TRIAGE "+
          json.dumps(out,sort_keys=True,ensure_ascii=False))


if __name__=="__main__":
    main()
