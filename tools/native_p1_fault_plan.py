#!/usr/bin/env python3
"""Versioned P1 external PA22 nFAULT calendar: source-clocked, fail-closed.

This is a QEMU ONLY physical external pin fixture. It NEVER edits Guest
firmware, MCPWM TZ, CPU or exception state, or simulates a recovery.
"""
import hashlib
import json
from pathlib import Path


class FaultPlanError(ValueError):
    pass


def load_fault_plan(path,stages):
    path=Path(path)
    raw=path.read_bytes()
    try:
        d=json.loads(raw)
    except (UnicodeError,ValueError) as exc:
        raise FaultPlanError("Invalid fault JSON") from exc
    keys={"schema","source","assert_frame","release_frame","expectation"}
    if type(d) is not dict or set(d)!=keys or (
        d["schema"]!="e62.native.external-fault.v1" or
        d["source"]!="pa22_nfault" or
        d["expectation"]!="OST2_LATCHED_AND_NO_AUTO_REARM"):
        raise FaultPlanError("Unknown source fault schema/expectation")
    total=sum(x[0] for x in stages)
    start=d["assert_frame"];stop=d["release_frame"]
    if (type(start) is not int or type(stop) is not int or
        not 0<start<stop<total or stop-start<10):
        raise FaultPlanError("Fault must assert and release inside virtual timeline")
    # The fault must occur with a declared positive-throttle command,
    # not prior to ARM, not in teardown, and not in another scenario.
    at=0;in_drive=False
    for duration,a,b,_ in stages:
        if at<=start<at+duration and (a>0 or b>0):
            in_drive=True
        at+=duration
    if not in_drive:
        raise FaultPlanError("No source-positive throttle during physical fault")
    return {
        "schema":d["schema"],"source":d["source"],
        "assert_frame":start,"release_frame":stop,
        "expected_ost_mask":0x20000,
        "sha256":hashlib.sha256(raw).hexdigest(),
        "scope":"NATIVE_VIRTUAL_CLOCK_EXTERNAL_INPUT_NOT_GUEST_MMIO",
        "verified_motor_recovery":False,
    }
