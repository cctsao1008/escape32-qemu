#!/usr/bin/env python3
"""E62 script-first Original Guest / native QEMU deterministic P1 test matrix.

No CLI, QEMU -S, Guest memory writes, fake BEMF, GDB, or WFI stepping.
Each case is a fresh QEMU boot from a pinned Guest ELF and versioned
1kHz external-FC physical PA26 DShot JSON, with a red/green P1 verdict.
The separate original-Guest physics and P0 strict gates remain intact.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.native_dshot_scenario import load_native_scenario

CASES={
    "smoke": ROOT/"scenarios/e62-native-p0-smoke.json",
    "gentle": ROOT/"scenarios/e62-native-p0-gentle.json",
    "direct20": ROOT/"scenarios/e62-native-p0-direct20.json",
    "steps": ROOT/"scenarios/e62-native-p0-steps.json",
    "ramp20_100ms":ROOT/"scenarios/e62-native-p1-ramp20-100ms.json",
    "ramp20_500ms":ROOT/"scenarios/e62-native-p1-ramp20-500ms.json",
}
DEFAULT_CASES=("smoke","gentle","direct20","steps")


def decide(probe_exit,analyzer_exit,verdict):
    """Never allow a diagnostic-only or historical wiring PASS to
    override a failed source clock, rotor, or Guest IRQ gate."""
    return (probe_exit==0 and analyzer_exit==0 and
            verdict.get("qualified") is True and
            verdict.get("status")=="PASS_P1_SIM_ONLY_OBSERVABILITY")


def run_command(argv,log_path,timeout):
    with log_path.open("w") as stream:
        try:
            p=subprocess.run(argv,stdout=stream,stderr=subprocess.STDOUT,
                             timeout=timeout,cwd=ROOT,check=False)
            return p.returncode,None
        except subprocess.TimeoutExpired:
            stream.write("SCRIPT_CASE_WALL_TIMEOUT_EXPIRED\n")
            return 124,"TIMEOUT"
        except OSError as exc:
            stream.write("SCRIPT_CASE_LAUNCH_ERROR: "+str(exc)+"\n")
            return 127,type(exc).__name__+": "+str(exc)


def run_case(*,name,scenario,qemu,elf,cfg,output,wall_timeout):
    stages,meta=load_native_scenario(scenario)
    prefix=output/("e62-p1-script-"+name)
    probe=prefix.with_suffix(".json")
    events=output/("e62-p1-script-"+name+".p0.events.log")
    verdict_path=output/("e62-p1-script-"+name+".p1.json")
    probe_log=output/("e62-p1-script-"+name+".probe.log")
    analyzer_log=output/("e62-p1-script-"+name+".p1.log")
    probe_args=[
        sys.executable,str(ROOT/"tests/e62_autonomous_native_motor_probe.py"),
        "--qemu",str(qemu),"--elf",str(elf),"--cfg-flash",str(cfg),
        "--scenario",str(scenario),
        "--wall-timeout-s",str(wall_timeout),
        "--artifact",str(probe),
    ]
    probe_rc,probe_error=run_command(
        probe_args,probe_log,wall_timeout+20)
    analyzer_args=[
        sys.executable,str(ROOT/"tools/native_p1_qualification.py"),
        "--scenario",str(scenario),"--evidence",str(probe),
        "--events",str(events),"--output",str(verdict_path),
    ]
    analyzer_rc,analyzer_error=run_command(
        analyzer_args,analyzer_log,60)
    try:
        verdict=json.loads(verdict_path.read_text())
    except (OSError,ValueError):
        verdict={"qualified":False,"status":"MISSING_P1_SOURCE_VERDICT",
                 "unwaived_observability_failures":["NO_READABLE_VERDICT"]}
    ok=decide(probe_rc,analyzer_rc,verdict)
    return {
        "case":name,"status":"PASS" if ok else "FAIL",
        "qualified":ok,"scenario_sha256":meta["sha256"],
        "source_frames_expected":meta["dshot_frames"],
        "probe_exit_code":probe_rc,"analyzer_exit_code":analyzer_rc,
        "probe_error":probe_error,"analyzer_error":analyzer_error,
        "failures":verdict.get("unwaived_observability_failures",[]),
        "first_dshot_mismatch":verdict.get("dshot_first_mismatch"),
        "peak_abs_rpm":verdict.get("peak_abs_rpm_in_positive_window"),
        "rotor_significant_direction_changes":verdict.get(
            "significant_rotor_direction_changes"),
        "startup_50rpm_delay_ms":verdict.get(
            "first_observed_50rpm_delay_ms"),
        "source_original_guest_pwm_pairs":verdict.get(
            "source_guest_closed_loop_pwm_pairs"),
        "artifacts":{
            "probe_json":str(probe),"probe_log":str(probe_log),
            "source_events":str(events),"p1_json":str(verdict_path),
            "p1_log":str(analyzer_log),
        },
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case",choices=tuple(CASES),action="append",
                        help="Repeat to select cases; default all three")
    parser.add_argument("--qemu",type=Path,
                        default=ROOT/".build/qemu-src/build/qemu-system-arm")
    parser.add_argument("--elf",type=Path,
                        default=ROOT/"baseline/e62-g13b3/firmware/AM13E-rev17.3.elf")
    parser.add_argument("--cfg-flash",type=Path,
                        default=ROOT/"artifacts/e62-g13b3-native-autonomous-cfg-flash.bin")
    parser.add_argument("--output",type=Path,
                        default=ROOT/"artifacts/e62-p1-scripted")
    parser.add_argument("--wall-timeout-s",type=int,default=300)
    args=parser.parse_args()
    if args.wall_timeout_s<20 or args.wall_timeout_s>1800:
        parser.error("Wall timeout must be in [20,1800] seconds")
    args.output.mkdir(parents=True,exist_ok=True)
    cases=list(dict.fromkeys(args.case or DEFAULT_CASES))
    results=[]
    for name in cases:
        print("E62_P1_SCRIPT_START "+name,flush=True)
        result=run_case(
            name=name,scenario=CASES[name],qemu=args.qemu,
            elf=args.elf,cfg=args.cfg_flash,output=args.output,
            wall_timeout=args.wall_timeout_s)
        results.append(result)
        print("E62_P1_SCRIPT_CASE "+json.dumps(result,sort_keys=True),
              flush=True)
    all_pass=all(r["qualified"] for r in results)
    matrix={
        "status":"PASS_P1_SCRIPTED_MATRIX" if all_pass else
                 "FAIL_P1_SCRIPTED_MATRIX",
        "qualified":all_pass,
        "original_guest_model":"ESCape32_REL17_3_PINNED_ELF",
        "host_guest_register_writes":False,
        "no_wfi_or_gdb":True,
        "sim_only":True,
        "hardware_or_propeller_qualified":False,
        "manual_cli_used":False,
        "cases":results,
    }
    file=args.output/"e62-p1-scripted-matrix.json"
    file.write_text(json.dumps(matrix,indent=2,sort_keys=True)+"\n")
    print("E62_P1_SCRIPT_MATRIX "+json.dumps({
        "status":matrix["status"],"report":str(file),
        "cases":[(r["case"],r["status"],r["failures"]) for r in results]
    },sort_keys=True),flush=True)
    raise SystemExit(0 if all_pass else 1)


if __name__=="__main__":
    main()
