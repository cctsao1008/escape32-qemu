#!/usr/bin/env python3
"""EXPERIMENT ONLY: independent preboot Direct20 FC and Guest startup A/B.

No QTest, Guest writes, or source replay substitution. Optional QMP
reads CPU register state ONLY after all external FC frames to identify a
stalled experimental Guest; never QMP cont/stop/step or memory writes. The unchanged
strict Original Rel17 P0/P1 qualification is NEVER called a PASS here.
Only compare byte-identical physical QEMU source and two separately
compiled original-policy and opt-in startup-policy firmware variants.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path

EVENT = re.compile(r"vns=(\d+) kind=(\w+) a=(-?\d+) b=(-?\d+) c=(-?\d+) d=(-?\d+) e=(-?\d+) f=(-?\d+)")
DSHOT = re.compile(r"\bkind=DSHOT a=(\d+)\b")
EXPECTED_FRAMES = 3300


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def readonly_qmp_cpu_snapshot(path):
    """QMP register query only: no Guest writes or CPU control."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(8)
        client.connect(str(path))
        src = client.makefile("rb")
        greeting = json.loads(src.readline())
        if "QMP" not in greeting:
            raise ValueError("No QMP greeting")
        def request(name, args=None):
            q = {"execute":name}
            if args is not None:
                q["arguments"]=args
            client.sendall((json.dumps(q)+"\n").encode())
            while True:
                x=json.loads(src.readline())
                if "return" in x:
                    return x["return"]
                if "error" in x:
                    raise ValueError(name+": "+str(x["error"]))
        request("qmp_capabilities")
        return {
            "query_status":request("query-status"),
            "query_cpus_fast":request("query-cpus-fast"),
            "info_registers":request("human-monitor-command",
                                    {"command-line":"info registers"}),
            "query_only_no_guest_control":True,
        }


def run(a):
    for p in (a.qemu, a.elf, a.cfg_flash):
        if not p.is_file():
            raise ValueError("Missing experimental source/ELF/config: " + str(p))
    if a.label not in ("control", "candidate"):
        raise ValueError("Expected only two unqualified A/B cases")
    a.artifact.parent.mkdir(parents=True, exist_ok=True)
    log = a.artifact.with_suffix(".qemu.log")
    qmp_path = Path("/tmp") / f"e62-exp-qmp-{os.getpid()}-{a.label}.sock"
    qmp_path.unlink(missing_ok=True)
    command = [
        str(a.qemu.resolve()), "-machine",
        "am13e23019,esc-sim=on,esc-sim-native-motor=on,"
        "esc-sim-nfault-asserted=off,esc-sim-experimental-fc-direct20=on",
        "-kernel", str(a.elf.resolve()),
        "-display", "none", "-serial", "none", "-monitor", "none",
        "-qmp", f"unix:{qmp_path},server=on,wait=off",
        "-icount", "shift=2,sleep=off,align=off",
        "-device", "loader,file=" + str(a.cfg_flash.resolve()) +
                   ",addr=0x4000,force-raw=on",
    ]
    report = {
        "schema": "e62.exp.bemf-first-cross.v1",
        "label": a.label,
        "result": "INCOMPLETE_EXPERIMENT",
        "original_guest_qualification": False,
        "motor_p1_qualified": False,
        "hardware_qualified": False,
        "host_guest_register_writes": False,
        "no_qtest_or_qmp": False,
        "qtest_used": False,
        "qmp_readonly_register_diagnostic_only": True,
        "source_is_real_qemu_virtual_clock": True,
        "motor_model_modified_by_this_runner": False,
        "elf_sha256": sha256(a.elf),
        "qemu_sha256": sha256(a.qemu),
        "cfg_sha256": sha256(a.cfg_flash),
        "source_log": str(log),
    }
    try:
        with log.open("wb") as fp:
            proc = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                    stderr=fp)
            last = -1
            try:
                deadline = time.monotonic() + a.wall_timeout_s
                with log.open("r", encoding="utf-8", errors="replace") as src:
                    while time.monotonic() < deadline:
                        line = src.readline()
                        if line:
                            m = DSHOT.search(line)
                            if m:
                                idx = int(m.group(1))
                                if idx != last + 1:
                                    raise ValueError("Missing/order-changed FC frame")
                                last = idx
                                if last == EXPECTED_FRAMES-1:
                                    break
                        elif proc.poll() is not None:
                            raise RuntimeError("QEMU died before 3300 frames")
                        else:
                            time.sleep(.05)
                    else:
                        raise TimeoutError("QEMU Direct20 source incomplete: " + str(last))
                if last == EXPECTED_FRAMES-1:
                    try:
                        report["passive_qmp_after_all_frames"] = (
                            readonly_qmp_cpu_snapshot(qmp_path))
                    except (OSError, ValueError, TypeError) as exc:
                        report["passive_qmp_error"] = str(exc)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        if last != EXPECTED_FRAMES-1:
            raise ValueError("Incomplete Direct20 frames")
        rows = []
        for line in log.open(encoding="utf-8", errors="replace"):
            m = EVENT.search(line)
            if m:
                t,kind,*d = m.groups()
                rows.append((int(t), kind, tuple(map(int,d))))
        onset = next((t for t,k,d in rows if k=="DSHOT" and d[2]>0),None)
        if onset is None:
            raise ValueError("No positive external PA26 source")
        cutoff = onset + 50_000_000
        after = [(t,k,d) for t,k,d in rows if t>=onset]
        def first(kind):
            return next((t for t,k,d in after if k==kind),None)
        first_pair = first("PWM_PAIR")
        first_cap = first("CAP1")
        first_timg = first("TIMG12")
        rotor = [(t,d) for t,k,d in after if k=="ROTOR" and t<cutoff]
        # The positive Direct20 stage is 1500ms; measuring only first
        # 50ms can hide later reversal and misclassify an unstable motor.
        # Original P1 strict logic is NOT altered by this experiment.
        full_positive = [(t,d) for t,k,d in after
                         if k=="ROTOR" and t<onset+1_500_000_000]
        if len(full_positive)<1490:
            raise ValueError("Missing full 1500ms rotor source")
        full_reverse = [(t,d) for t,d in full_positive if d[0]<=-50000]
        first_reverse = next((t for t,d in rotor if d[0]<=-50000),None)
        first_neg_torque = next((t for t,d in rotor if d[5]<-100000),None)
        pairs = [(t,d[0],d[1]) for t,k,d in after if k=="PWM_PAIR" and t<cutoff]
        report["read_only_source_counts"] = {
            k: sum(1 for t,event_kind,d in rows if event_kind==k)
            for k in ("DSHOT","WWDT_FEED","PWM_PAIR","ROTOR","CAP1",
                      "TIMG12","SWITCH","OC_FRONTEND")}
        report["source_last_wwdt_feed_ms"] = (
            round(max((t for t,k,d in rows if k=="WWDT_FEED"),default=0)/1e6,6))
        report["positive_dshot_ms"] = round(onset/1e6,6)
        if len(rotor)<20 or first_cap is None or first_pair is None:
            raise ValueError("Missing early rotor/CAP1/physical PWM source")
        def ms(t): return round((t-onset)/1e6,6) if t is not None else None
        report.update(
            result="EXPERIMENT_SOURCE_CAPTURED_NOT_P1",
            source_frames=last+1,
            first_positive_dshot_ns=onset,
            first_cap1_ms=ms(first_cap),
            second_cap1_ms=ms(next((t for t,k,d in after if k=="CAP1" and t>first_cap),None)),
            first_timg12_ms=ms(first_timg),
            first_pair_ms=ms(first_pair),
            first_change_pair_ms=ms(pairs[1][0]) if len(pairs)>1 else None,
            first_reverse_50rpm_ms=ms(first_reverse),
            first_negative_torque_ms=ms(first_neg_torque),
            full_positive_window_ms=1500,
            full_positive_rotor_samples=len(full_positive),
            full_positive_min_rpm=min(d[0] for t,d in full_positive)/1000,
            full_positive_max_rpm=max(d[0] for t,d in full_positive)/1000,
            full_positive_reverse_50rpm_samples=len(full_reverse),
            full_positive_first_reverse_ms=ms(full_reverse[0][0]) if full_reverse else None,
            first_50ms_pwm_pairs=len(pairs),
            first_50ms_rotor_samples=len(rotor),
            first_50ms_min_rpm=min(d[0] for t,d in rotor)/1000,
            first_50ms_max_rpm=max(d[0] for t,d in rotor)/1000,
            first_50ms_power_pair_sequence=[dict(ms=ms(t),pair_code=c,mask=mask)
                                             for t,c,mask in pairs[:12]],
        )
        return report
    finally:
        qmp_path.unlink(missing_ok=True)
        a.artifact.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")


def compare(a):
    control=json.loads(a.control.read_text())
    candidate=json.loads(a.candidate.read_text())
    result={
        "schema":"e62.exp.bemf-first-cross-compare.v1",
        "classification":"EXPERIMENT_NOT_QUALIFIED",
        "motor_p1_qualified":False,"hardware_qualified":False,
        "original_rel17_reference_elf_unchanged":True,
        "no_strict_original_gate_waiver":True,
    }
    try:
        if any(x["result"]!="EXPERIMENT_SOURCE_CAPTURED_NOT_P1"
               for x in (control,candidate)):
            raise ValueError("Unfinished source test")
        if control["qemu_sha256"] != candidate["qemu_sha256"] or (
                control["cfg_sha256"] != candidate["cfg_sha256"]):
            raise ValueError("QEMU/Guest cfg changed between A/B")
        if control["elf_sha256"]==candidate["elf_sha256"]:
            raise ValueError("Experimental flag did not change Guest ELF")
        if any(x["source_frames"]!=EXPECTED_FRAMES for x in (control,candidate)):
            raise ValueError("Missing FC sources")
        baseline = control["first_timg12_ms"]
        trial = candidate["first_timg12_ms"]
        result.update(
            original_policy_first_cap1_ms=control["first_cap1_ms"],
            candidate_first_cap1_ms=candidate["first_cap1_ms"],
            control_first_timg12_ms=baseline,
            candidate_first_timg12_ms=trial,
            control_reverse_50rpm_ms=control["first_reverse_50rpm_ms"],
            candidate_reverse_50rpm_ms=candidate["first_reverse_50rpm_ms"],
            fixed_initial_capture_before_5ms=control["first_cap1_ms"]<5,
            candidate_early_timg12=(trial is not None and
                                   baseline is not None and trial<baseline),
            candidate_no_early_reverse=candidate["first_reverse_50rpm_ms"] is None,
            candidate_full_positive_reverse_samples=candidate["full_positive_reverse_50rpm_samples"],
            candidate_no_full_positive_reverse=(
                candidate["full_positive_reverse_50rpm_samples"]==0),
            control_full_positive_reverse_samples=control["full_positive_reverse_50rpm_samples"],
        )
        result["classification"]=("EARLY_SOURCE_IMPROVED_NOT_P1"
              if result["candidate_early_timg12"] and
                 result["candidate_no_early_reverse"] and
                 result["candidate_no_full_positive_reverse"]
              else "FAIL_EXPERIMENT_NOT_FIXED")
    except (KeyError,TypeError,ValueError) as e:
        result.update(classification="FAIL_EXPERIMENT_INVALID_EVIDENCE",
                      reason=str(e))
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("E62_EXPERIMENTAL_BEMF_A_B "+json.dumps(result,sort_keys=True))
    return 0 if result["classification"]=="EARLY_SOURCE_IMPROVED_NOT_P1" else 1


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sp=p.add_subparsers(dest="mode",required=True)
    r=sp.add_parser("run")
    r.add_argument("--qemu",type=Path,required=True)
    r.add_argument("--elf",type=Path,required=True)
    r.add_argument("--cfg-flash",type=Path,required=True)
    r.add_argument("--label",choices=("control","candidate"),required=True)
    r.add_argument("--artifact",type=Path,required=True)
    r.add_argument("--wall-timeout-s",type=int,default=250)
    c=sp.add_parser("compare")
    c.add_argument("--control",type=Path,required=True)
    c.add_argument("--candidate",type=Path,required=True)
    c.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.mode=="run":
        print("E62_EXPERIMENTAL_DIRECT20 "+json.dumps(run(args),sort_keys=True))
        return 0
    return compare(args)


if __name__=="__main__":
    raise SystemExit(main())
