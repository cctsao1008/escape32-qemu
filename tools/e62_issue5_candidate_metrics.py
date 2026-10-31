#!/usr/bin/env python3
"""Candidate ONLY QEMU motor startup/restart metrics. NEVER Original Rel17 P1."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p0_strict import parse_events

ORIG="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
def audit(evs, evidence):
    sha=evidence.get("candidate_elf_sha256")
    assert isinstance(sha,str) and len(sha)==64 and sha!=ORIG
    assert evidence.get("experimental_candidate_not_original") is True
    assert evidence.get("host_guest_register_writes") is False
    assert evidence.get("synthetic_timed_bemf_enabled") is False
    assert evidence.get("used_guest_wfi_or_gdb") is False
    dshot=[e for e in evs if e["kind"]=="DSHOT"]
    assert len(dshot)==evidence["configured_dshot_frames"],"source frame count"
    vns=[e for e in dshot if e["data"][1]==1]
    start=vns[0]["vns"]
    stages={}
    for n in (1,3):
        ds=[e for e in dshot if e["data"][1]==n]
        assert ds,("stage missing",n)
        t0,t1=ds[0]["vns"],ds[-1]["vns"]+1000000
        samples=[e for e in evs if e["kind"]=="ROTOR" and t0<=e["vns"]<t1]
        assert len(samples)>100
        speeds=[e["data"][0]*.001 for e in samples]
        pairs=[e for e in evs if e["kind"]=="PWM_PAIR" and t0<=e["vns"]<t1]
        cap=[e for e in evs if e["kind"]=="CAP1" and t0<=e["vns"]<t1]
        stages[str(n)]={"min_rpm":round(min(speeds),3),
                        "max_rpm":round(max(speeds),3),
                        "final_rpm":round(speeds[-1],3),
                        "negative_below_50rpm_count":sum(x < -50 for x in speeds),
                        "source_pwm_pair_count":len(pairs),
                        "source_cap1_count":len(cap)}
    no_reverse=all(stages[str(n)]["negative_below_50rpm_count"]==0 for n in (1,3))
    sustained_forward=all(stages[str(n)]["final_rpm"]>50 for n in (1,3))
    return {"status":"CANDIDATE_ONLY_SOURCE_DIAGNOSTIC",
            "candidate_sha256":sha,
            "original_sha256_unchanged":ORIG,
            "source_dshot_frames":len(dshot),
            "first_and_second_start":stages,
            "no_significant_reverse":no_reverse,
            "forward_at_end_of_demands":sustained_forward,
            "candidate_start_reacquisition_qualified":no_reverse and sustained_forward,
            "original_p1_qualified":False,
            "not_hardware_qualified":True}

def main():
    p=argparse.ArgumentParser()
    for name in ("events","evidence","output"):
        p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args()
    report=audit(parse_events(a.events.read_text().splitlines()),
                 json.loads(a.evidence.read_text()))
    a.output.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print(json.dumps(report,indent=2))
    if not report["candidate_start_reacquisition_qualified"]:
        sys.exit(2) # real candidate FAIL visible
if __name__=="__main__":main()
