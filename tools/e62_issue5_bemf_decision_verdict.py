"""Issue #5: fail-closed source Guest decision diagnostics; SIM_ONLY.

This validates *actual decoded Guest records* and reports early BEMF
rejections. It deliberately does not match a record to the 47V +8.832ms
CAP1 without independent time/sequence correspondence.
"""
import argparse
import json
from pathlib import Path


def audit(doc):
    history = doc.get("issue5_bemf_first_history")
    if not isinstance(history, dict) or not isinstance(history.get("entries"), list):
        raise ValueError("MISSING_GUEST_FIRST_HISTORY")
    rows = history["entries"]
    if not rows:
        raise ValueError("EMPTY_GUEST_FIRST_HISTORY")
    if len(rows) > 64 or any(type(row.get("seq")) is not int or
                             row["seq"] != i for i, row in enumerate(rows)):
        raise ValueError("FIRST_HISTORY_SEQUENCE_INVALID")
    if type(history.get("seq_after")) is not int or history["seq_after"] < len(rows):
        raise ValueError("FIRST_HISTORY_COUNTER_INVALID")
    counts = {"ACCEPTED": 0, "REJECTED_EARLY": 0, "TIMEOUT": 0}
    rejects = []
    for row in rows:
        decision = row.get("decision")
        capture = row.get("capture_us")
        prior = row.get("ival_before")
        delay = row.get("delay_us")
        if decision not in counts or any(type(v) is not int for v in (capture,prior,delay)):
            raise ValueError("BEMF_RECORD_INVALID")
        counts[decision] += 1
        if prior <= 0 or prior > 2**30:
            raise ValueError("BEMF_INTERVAL_INVALID")
        if decision == "REJECTED_EARLY":
            if capture < 0 or capture >= (prior >> 1) or delay != 0:
                raise ValueError("EARLY_REJECTION_CONTRADICTS_SOURCE_POLICY")
            rejects.append({"seq": row["seq"], "tick": row.get("tick"),
                            "capture_us": capture, "ival_before": prior,
                            "threshold_us": prior >> 1})
        elif decision == "ACCEPTED":
            if capture < 0 or delay <= 0:
                raise ValueError("ACCEPTED_RECORD_INVALID")
        else:
            if capture != 0 or delay != 0:
                raise ValueError("TIMEOUT_RECORD_INVALID")
    return {"source_guest_records": len(rows), "counts": counts,
            "early_rejections": rejects,
            "history_truncated": bool(history.get("first_history_capped")),
            "target_cap1_1508_832ms_classification": "NOT_PROVEN_BY_UNALIGNED_HISTORY",
            "hardware_qualified": False}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("artifact",type=Path)
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    result=audit(json.loads(a.artifact.read_text()))
    text=json.dumps(result,indent=2,sort_keys=True)+"\n"
    if a.output:
        a.output.write_text(text)
    print(text,end="")


if __name__=="__main__":
    main()
