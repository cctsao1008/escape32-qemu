#!/usr/bin/env python3
"""Read-only native No-WFI QEMU source-event adapter for E62 WebGUI.

Consumes ONLY the preexisting 'E62_P0_EVENT' stderr trace. Never opens a
QTest/GDB socket, writes Guest memory, modifies QEMU virtual time, changes
motor physics, or invents source events. Actual rotor/current are SIM_ONLY.
BEMF_FRONTEND values are ADC CODES, not measured physical voltages.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.native_p0_strict import EVENT, KINDS

FORMAT="e62.sitl.native-source.v1"
ELF="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
EVENT_KINDS={
    "DSHOT","PWM_PAIR","CAP1","CAP1_ACK","ECAP1_CAP1_READ",
    "T12_LOAD","T12_START","T12_STOP","TIMG12","TIMG12_ACK",
    "CMP_FILTER","NFAULT_EDGE","WWDT_FEED","THROT_SET",
    "SWITCH_FOCUS",
}
MAX_SAMPLES=200000
MAX_EVENTS=100000
MAX_PENDING_EVENTS=256
MASK_FRESH_NS=2_000_000

class SourceTraceError(ValueError):
    pass

def read_source_line(line):
    """Ignore non-event QEMU messages; reject *malformed* event records."""
    if "E62_P0_EVENT " not in line:
        return None
    match=EVENT.search(line)
    if not match:
        raise SourceTraceError("Malformed native QEMU source event")
    kind=match.group(3)
    if kind not in KINDS:
        raise SourceTraceError("Unknown native QEMU source event "+kind)
    return {
        "seq":int(match.group(1)), "vns":int(match.group(2)), "kind":kind,
        "data":[int(match.group(i)) for i in range(4,10)],
    }

class NativeSourceReducer:
    """One timestamped sample per real model BEMF_FRONTEND publish (~1 ms).

    No line interpolation; the field values are the latest event-sourced
    values, with an explicit freshness window for physical PWM six-pad
    switching (historical SWITCH trace is bounded to 120 ms).
    """
    def __init__(self, elf_sha256=ELF):
        if elf_sha256!=ELF:
            raise SourceTraceError("Pinned Original Rel17.3 ELF required")
        self.elf_sha256=elf_sha256
        self.last_seq=0
        self.last_vns=-1
        self.last_sample_vns=-1
        self.rotor=None
        self.rotor_time=None
        self.mask=None
        self.mask_time=None
        self.mask_source=None
        self.gate=None
        self.pair=None
        self.last_dshot=None
        self.last_dshot_time=None
        self.last_frame=None
        self.cap1_count=0
        self.timg12_count=0
        self.wwdt_feed_count=0
        self.last_cap1=None
        self.last_timg12=None
        self.pending=[]
        self.total_samples=0
        self.total_discrete_events=0
        self.total_input_events=0
        self.first_time=None

    @property
    def metadata(self):
        return {
            "format":FORMAT,"mode":"native-source","elf_sha256":self.elf_sha256,
            "timebase":"QEMU_CLOCK_VIRTUAL",
            "sample_origin":"REAL_BEMF_FRONTEND_FOLLOWING_ROTOR_SOURCE_CALLBACK",
            "source":"QEMU_E62_P0_EVENT_READ_ONLY",
            "model":"SIM_ONLY_UNCALIBRATED_ECX87_KV147",
            "bemf_unit":"ADC_12BIT_CODE_NOT_VOLTS",
            "pwm_unit":"LAST_ACTUAL_SIX_PAD_MASK_NOT_DUTY",
            "no_guest_memory_writes":True,
            "not_qualified_motor_or_hardware":True,
        }

    def ingest(self, event):
        seq=event["seq"];vns=event["vns"];kind=event["kind"];d=event["data"]
        if (seq!=self.last_seq+1 or vns<self.last_vns or vns<0 or
            len(d)!=6 or kind not in KINDS):
            raise SourceTraceError(
                "Gap/time reversal/invalid source record at seq="+str(seq))
        self.last_seq=seq;self.last_vns=vns
        self.total_input_events+=1
        if self.first_time is None:self.first_time=vns

        if kind=="ROTOR":
            self.rotor={
                "rpm":d[0]/1000,"theta_mrad":d[1],
                "currents_a":[d[i]/1000 for i in (2,3,4)],
                "torque_nm":d[5]/1e6,
            }
            self.rotor_time=vns
        elif kind in ("SWITCH","SWITCH_FOCUS"):
            self.mask=d[0]&0x3f
            self.mask_time=vns
            self.mask_source=kind
            self.gate=bool(d[1])
        elif kind=="PWM_PAIR":
            self.pair=d[0]
        elif kind=="DSHOT":
            self.last_frame=d[0]
            self.last_dshot=d[2]
            self.last_dshot_time=vns
        elif kind=="CAP1":
            self.cap1_count+=1
            self.last_cap1=d[0]
        elif kind=="TIMG12":
            self.timg12_count+=1
            self.last_timg12=vns
        elif kind=="WWDT_FEED":
            self.wwdt_feed_count+=1

        if kind in EVENT_KINDS:
            if len(self.pending)>=MAX_PENDING_EVENTS:
                raise SourceTraceError("Source events exceed safe packet budget")
            self.pending.append({
                "seq":seq,"t_ns":vns,"kind":kind,"data":list(d),
            })
            self.total_discrete_events+=1
            if self.total_discrete_events>MAX_EVENTS:
                raise SourceTraceError("Source discrete event budget exceeded")

        if kind!="BEMF_FRONTEND":
            return None
        if (self.rotor is None or self.rotor_time is None or
            self.rotor_time!=vns or vns<=self.last_sample_vns):
            raise SourceTraceError(
                "BEMF frame missing same-clock real ROTOR source")
        if self.total_samples>=MAX_SAMPLES:
            raise SourceTraceError("Sample budget exceeded")
        self.last_sample_vns=vns
        self.total_samples+=1
        mask_is_fresh=(self.mask_time is not None and
                       0<=vns-self.mask_time<=MASK_FRESH_NS)
        sample={
            "t_ns":vns,"source_seq":seq,
            "motor_rpm":self.rotor["rpm"],
            "theta_mrad":self.rotor["theta_mrad"],
            "torque_nm":self.rotor["torque_nm"],
            "phase_currents_a":self.rotor["currents_a"],
            "bemf_codes":list(d[:3]),
            "bemf_selected_phase":d[3],
            "bemf_dac_code":d[4],
            "cmp_filtered":bool(d[5]),
            "pwm_six_pad_mask":self.mask if mask_is_fresh else None,
            "pwm_mask_source_kind":self.mask_source if mask_is_fresh else None,
            "pwm_gate":self.gate if mask_is_fresh else None,
            "pwm_pair":self.pair,
            "last_dshot_raw":self.last_dshot,
            "last_dshot_frame":self.last_frame,
            "last_dshot_ns":self.last_dshot_time,
            "cap1_count":self.cap1_count,
            "timg12_count":self.timg12_count,
            "wwdt_feed_count":self.wwdt_feed_count,
            "last_cap1_ticks":self.last_cap1,
            "last_timg12_ns":self.last_timg12,
        }
        events=self.pending
        self.pending=[]
        return {"sample":sample,"events":events}

    def finish(self):
        return {
            "format":FORMAT,
            "observed_source_events":self.total_input_events,
            "observed_samples":self.total_samples,
            "observed_discrete_events":self.total_discrete_events,
            "last_seq":self.last_seq,
            "last_virtual_ns":self.last_vns,
            "unpublished_tail_events":len(self.pending),
            "strict_extended_gate":"NOT_EXECUTED_BY_LIVE_TELEMETRY",
            "hardware_qualified":False,
            "motor_p1_stability_qualified":False,
        }

def convert(lines, *, elf_sha256=ELF):
    reducer=NativeSourceReducer(elf_sha256)
    samples=[];events=[]
    for line in lines:
        e=read_source_line(line)
        if e is not None:
            frame=reducer.ingest(e)
            if frame is not None:
                samples.append(frame["sample"])
                events.extend(frame["events"])
    if not samples:
        raise SourceTraceError("No real ROTOR/BEMF_FRONTEND source samples")
    return {
        "format":FORMAT,"metadata":reducer.metadata,
        "scope":"SIM_ONLY_NATIVE_NO_WFI_SOURCE_ONLY",
        "capture_state":"SOURCE_LOG_COMPLETE",
        "samples":samples,"events":events,
        "summary":reducer.finish(),
        "native_result":None,
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--elf",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if hashlib.sha256(a.elf.read_bytes()).hexdigest()!=ELF:
        p.error("Original Guest pinned ELF SHA256 mismatch")
    with a.events.open(encoding="utf-8",errors="replace") as stream:
        out=convert(stream)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(out,allow_nan=False,separators=(",",":"))+"\n")
    print("E62_NATIVE_SOURCE_TRACE "+json.dumps({
        "status":"SOURCE_TRACE_CONVERTED_READ_ONLY_NOT_MOTOR_PASS",
        "samples":len(out["samples"]),"events":len(out["events"]),
        "last_seq":out["summary"]["last_seq"],
        "output":str(a.output)
    }))
if __name__=="__main__":
    main()
