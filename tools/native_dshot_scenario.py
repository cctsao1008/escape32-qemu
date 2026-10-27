#!/usr/bin/env python3
"""Strict versioned native flight-controller DShot600 scenario compiler.

All timings and frames execute inside QEMU virtual clock via PA26.
Never wait for original Guest receiver readiness or write Guest memory.
"""
import hashlib
import json
from pathlib import Path

SHA="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
SCHEMA="e62.native.dshot.v1"


class ScenarioError(ValueError):
    pass


def _checked(n,name,lo,hi):
    if type(n) is not int or not lo<=n<=hi:
        raise ScenarioError(f"{name} must be integer {lo}..{hi}")
    return n


def load_native_scenario(path):
    path=Path(path)
    raw=path.read_bytes()
    try:
        doc=json.loads(raw)
    except (ValueError,UnicodeError) as exc:
        raise ScenarioError("Malformed DShot JSON") from exc
    keys={"schema","name","target_elf_sha256","protocol",
          "frame_period_ns","guest_ready_gating","stages"}
    if type(doc) is not dict or set(doc)!=keys:
        raise ScenarioError("Unsupported or missing top-level keys")
    if doc["schema"]!=SCHEMA or doc["protocol"]!="DSHOT600" or (
        doc["target_elf_sha256"]!=SHA or
        doc["frame_period_ns"]!=1000000 or
        doc["guest_ready_gating"] is not False):
        raise ScenarioError("Native QEMU virtual-1kHz DShot/ELF contract mismatch")
    stages=doc["stages"]
    if type(stages) is not list or not 2<=len(stages)<=16:
        raise ScenarioError("Require 2..16 stages")
    out=[]
    for i,s in enumerate(stages):
        if type(s) is not dict or s.get("kind") not in ("hold","ramp"):
            raise ScenarioError("Unsupported stage")
        ms=_checked(s.get("duration_ms"),"duration_ms",10,120000)
        if s["kind"]=="hold":
            if set(s)!={"kind","duration_ms","permille"}:
                raise ScenarioError("Unknown hold keys")
            n=_checked(s["permille"],"permille",0,1000)
            out.append((ms,n,n,1))
        else:
            if set(s)!={"kind","duration_ms","from_permille",
                          "to_permille","update_ms"}:
                raise ScenarioError("Unknown ramp keys")
            a=_checked(s["from_permille"],"from_permille",0,1000)
            b=_checked(s["to_permille"],"to_permille",0,1000)
            update=_checked(s["update_ms"],"update_ms",1,ms)
            if ms%update or ((b-a)*update)%ms:
                raise ScenarioError("Ramp must be exactly integer-permille representable")
            if out and out[-1][2]!=a:
                raise ScenarioError("Ramp start must equal prior output")
            out.append((ms,a,b,update))
    if out[0][1:3]!=(0,0) or out[-1][1:3]!=(0,0):
        raise ScenarioError("Start/end must be continuous DShot=0")
    total=sum(s[0] for s in out)
    if total>180000:
        raise ScenarioError("Bounded scenario exceeds 180s")
    return out,{
        "schema":SCHEMA,"name":doc["name"],
        "sha256":hashlib.sha256(raw).hexdigest(),
        "source_path":str(path),
        "dshot_frames":total,
        "stages":out,
        "guest_ready_gating":False,
        "frame_period_ns":1000000,
        "original_elf_sha256":SHA,
        "scope":"NATIVE_CONTINUOUS_PA26_NOT_GUEST_WRITES"
    }
