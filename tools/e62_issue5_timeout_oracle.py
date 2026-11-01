"""Issue #5: fail-closed verifier for BEMF loss-of-sync output safety.

Consumes *recorded* time-ordered guest/peripheral events. Does not synthesize
QEMU results or treat a host unit test as a source-driven qualification.

Input JSON: {"schema":"e62.bemf-timeout-trace.v1","source":"native_qemu",
 "firmware_sha256":"<64 lowercase hex>","qemu_sha":"<40 lowercase hex>",
 "events":[{"t_ns":integer,"kind":"BEMF_TIMEOUT"},
           {"t_ns":integer,"kind":"PWM_SIX","mask":0..63},
           {"t_ns":integer,"kind":"GATE_ENABLE","enabled":false},
           {"t_ns":integer,"kind":"TIMG12_COMMUTATION"}]}
For a real source trace, include periodic PWM_SIX and GATE_ENABLE observations
from before timeout through the entire post-timeout observation window.
"""
import argparse
import json
import re
from pathlib import Path

SCHEMA = "e62.bemf-timeout-trace.v1"
KINDS = {"BEMF_TIMEOUT", "PWM_SIX", "GATE_ENABLE", "TIMG12_COMMUTATION"}


def audit(doc, window_ns=2_000_000):
    failures = []
    if doc.get("schema") != SCHEMA:
        failures.append("SCHEMA_INVALID")
    if doc.get("source") != "native_qemu":
        failures.append("SOURCE_NOT_NATIVE_QEMU")
    if not re.fullmatch(r"[0-9a-f]{64}", str(doc.get("firmware_sha256", ""))):
        failures.append("FIRMWARE_SHA_INVALID")
    if not re.fullmatch(r"[0-9a-f]{40}", str(doc.get("qemu_sha", ""))):
        failures.append("QEMU_SHA_INVALID")
    events = doc.get("events")
    if not isinstance(events, list) or not events:
        return {"qualified": False, "failures": failures + ["EVENTS_MISSING"]}
    last = -1
    for event in events:
        if (not isinstance(event, dict) or
            type(event.get("t_ns")) is not int or event["t_ns"] < 0 or
            event["t_ns"] < last or event.get("kind") not in KINDS):
            return {"qualified": False, "failures": failures + ["EVENT_INVALID_OR_UNORDERED"]}
        last = event["t_ns"]
        if event["kind"] == "PWM_SIX" and (
            type(event.get("mask")) is not int or not 0 <= event["mask"] <= 63):
            failures.append("PWM_SAMPLE_INVALID")
        if event["kind"] == "GATE_ENABLE" and type(event.get("enabled")) is not bool:
            failures.append("GATE_SAMPLE_INVALID")
    timeout = [e for e in events if e["kind"] == "BEMF_TIMEOUT"]
    if len(timeout) != 1:
        failures.append("TIMEOUT_NOT_UNIQUE")
        return {"qualified": False, "failures": failures}
    t0 = timeout[0]["t_ns"]
    before = [e for e in events if e["t_ns"] < t0]
    after = [e for e in events if t0 <= e["t_ns"] <= t0 + window_ns]
    if not any(e["kind"] == "PWM_SIX" and e.get("mask", 0) != 0 for e in before):
        failures.append("NO_PRIOR_ENERGIZED_PWM")
    if not any(e["kind"] == "GATE_ENABLE" and e.get("enabled") is True for e in before):
        failures.append("NO_PRIOR_GATE_ENABLE")
    if not after or events[-1]["t_ns"] < t0 + window_ns:
        failures.append("POST_TIMEOUT_WINDOW_INCOMPLETE")
    pwms = [e for e in after if e["kind"] == "PWM_SIX"]
    gates = [e for e in after if e["kind"] == "GATE_ENABLE"]
    if len(pwms) < 2 or len(gates) < 2:
        failures.append("POST_TIMEOUT_SAMPLING_INSUFFICIENT")
    if any(e["kind"] == "TIMG12_COMMUTATION" for e in after):
        failures.append("STALE_COMMUTATION_AFTER_TIMEOUT")
    if any(e["kind"] == "PWM_SIX" and e.get("mask") != 0 for e in after):
        failures.append("ENERGIZED_PWM_AFTER_TIMEOUT")
    if any(e["kind"] == "GATE_ENABLE" and e.get("enabled") is not False for e in after):
        failures.append("GATE_ENABLED_AFTER_TIMEOUT")
    return {"qualified": not failures, "failures": sorted(set(failures)),
            "timeout_ns": t0, "observation_window_ns": window_ns}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--window-ns", type=int, default=2_000_000)
    args = parser.parse_args()
    if args.window_ns <= 0:
        parser.error("--window-ns must be positive")
    try:
        result = audit(json.loads(args.trace.read_text()), args.window_ns)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["qualified"] else 1)


if __name__ == "__main__":
    main()
