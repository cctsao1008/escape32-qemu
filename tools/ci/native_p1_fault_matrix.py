#!/usr/bin/env python3
"""Combine *independent* original Guest fault/CRC negative cases for P1.

These tests are separate boot/device experiments (some use GDB/WFI).
They do NOT establish autonomous running-motor fault recovery, coast
behavior after signal loss or safe re-arm after a latched fault.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.ci.safety_qualification import verify_all
from tools.ci.dshot_crc_qualification import verify_pair


def evaluate(safety_cases,good_crc,bad_crc):
    safety=verify_all(safety_cases)
    crc=verify_pair(good_crc,bad_crc)
    errors=list(safety.get("issues",[]))
    errors += ["bad_dshot_crc:"+e for e in crc]
    return {
        "status":"PASS_P1_SEPARATE_NEGATIVE_CONTROLS" if not errors else
                 "FAIL_P1_SEPARATE_NEGATIVE_CONTROLS",
        "qualified":not errors,
        "verified_independent_trip_cases":safety.get("independent_cases_passed",[]),
        "verified_independent_crc_pair":not crc,
        "issues":errors,
        "fault_test_mode":"SEPARATE_ORIGINAL_GUEST_WFI_AND_PERIPHERAL_ROUTING",
        "native_no_wfi_motor_under_load_fault_recovery":False,
        "dshot_signal_loss_timeout_and_fresh_rearm":False,
        "no_guest_memory_pwm_irq_or_cpu_state_writes_for_fault_source":True,
        "hardware_and_silicon_qualified":False,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    cases={}
    for name in ("nfault","oc-u","oc-v","oc-w"):
        f=a.input_dir/f"e62-safety-{name}.json"
        if f.exists():
            cases[name]=json.loads(f.read_text())
    valid=a.input_dir/"e62-dshot-valid-native.json"
    invalid=a.input_dir/"e62-dshot-bad-crc-native.json"
    positive=json.loads(valid.read_text()) if valid.exists() else []
    negative=json.loads(invalid.read_text()) if invalid.exists() else []
    report=evaluate(cases,positive,negative)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("E62_NATIVE_P1_FAULT_MATRIX "+json.dumps(report,sort_keys=True))
    if not report["qualified"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
