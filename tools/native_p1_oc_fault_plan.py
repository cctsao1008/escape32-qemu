#!/usr/bin/env python3
"""Versioned SIM_ONLY external current-SENSE overrange pulse at source FC frames.

This fixture is NOT physical motor torque or current, and does NOT
write Guest PWM/CMPSS/TZ registers or simulate a load current.
"""
import hashlib
import json
from pathlib import Path

MAP={"oc-w":0,"oc-v":1,"oc-u":2}

def load_oc_plan(path, stages):
    raw=Path(path).read_bytes()
    d=json.loads(raw)
    if (type(d) is not dict or set(d)!={
        "schema","source","phase","assert_frame","release_frame","expectation"} or
        d["schema"]!="e62.native.external-oc-sense.v1" or
        d["source"]!="adc_like_current_sense_overrange" or
        d["expectation"]!="OST3_LATCHED_GATE_SAFE_OFF_NO_REARM" or
        d["phase"] not in MAP):
        raise ValueError("Unknown external current-sense overrange plan")
    start,stop=d["assert_frame"],d["release_frame"]
    total=sum(s[0] for s in stages)
    if (type(start) is not int or type(stop) is not int or
        not 0<start<stop<total or stop-start<10):
        raise ValueError("Overrange source must assert/release inside DShot scenario")
    idx=0
    for duration,a,b,_ in stages:
        if idx<=start<idx+duration and (a>0 or b>0):break
        idx+=duration
    else:
        raise ValueError("Current-sense overrange must occur during source-positive drive")
    return {"schema":d["schema"],"phase":d["phase"],
            "channel":MAP[d["phase"]],"assert_frame":start,
            "release_frame":stop,
            "code":4095,
            "scope":"EXTERNAL_ADC_LIKE_SENSOR_OVERRANGE_NOT_PHYSICAL_MOTOR_CURRENT",
            "never_guest_register_write":True,
            "sha256":hashlib.sha256(raw).hexdigest(),
            "hardware_qualified":False}
