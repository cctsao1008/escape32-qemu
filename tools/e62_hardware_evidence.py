#!/usr/bin/env python3
"""E62 physical PWM/current/protection/thermal evidence intake (fail-closed).

Never infer physical measurement from QEMU, source code or a host unit fixture.
The tool only validates provenance/completeness. Approval remains external.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

# Bench conditions intentionally do not imply that a board exists.
# Numeric performance targets are those in the supplied Queen Bee baseline;
# a blank quantitative trip or thermal criterion must remain OPEN.
REQUIRED = (
    ("pwm_phase_sequence", "PWM", "sequence", "H1"),
    ("pwm_carrier_frequency", "PWM", "Hz", "H1"),
    ("pwm_gate_deadtime", "PWM", "ns", "H1"),
    ("pwm_same_leg_overlap", "PWM", "ns", "H1"),
    ("pwm_vds_overshoot", "PWM", "V", "H2"),
    ("pwm_gate_drive_voltage", "PWM", "V", "H1"),
    ("motor_phase_current_rms", "CURRENT", "A", "H2"),
    ("motor_phase_current_peak", "CURRENT", "A", "H3"),
    ("dc_bus_current", "CURRENT", "A", "H2"),
    ("dc_bus_input_power", "CURRENT", "W", "H2"),
    ("nfault_to_all_pwm_off", "PROTECTION", "us", "H1"),
    ("oc_u_to_all_pwm_off", "PROTECTION", "us", "H1"),
    ("oc_v_to_all_pwm_off", "PROTECTION", "us", "H1"),
    ("oc_w_to_all_pwm_off", "PROTECTION", "us", "H1"),
    ("fault_recovery_behavior", "PROTECTION", "text", "H1"),
    ("mosfet_hotspot", "THERMAL", "degC", "H2"),
    ("electrolytic_hotspot", "THERMAL", "degC", "H2"),
    ("gate_driver_hotspot", "THERMAL", "degC", "H2"),
    ("ambient_air", "THERMAL", "degC", "H2"),
    ("steady_state_test_duration", "THERMAL", "s", "H2"),
    ("peak_warm_start_temperature", "THERMAL", "degC", "H3"),
)
COLUMNS = (
    "metric_id", "domain", "unit", "condition_id", "requirement_ref",
    "measured_value", "raw_trace_ref", "board_revision", "board_serial",
    "firmware_sha", "instrument_id", "measured_at_utc", "capture_status",
    "acceptance_criteria_ref", "notes",
)
TEXT_UNITS = {"sequence", "text"}


def evaluate_hardware_rows(rows):
    """Validate all four domains, without declaring physical compliance."""
    if not isinstance(rows, list):
        raise ValueError("Hardware intake requires CSV rows")
    expected = {x[0]: x for x in REQUIRED}
    observed = {}
    counts = {domain: {"total": 0, "captured": 0}
              for domain in ("PWM", "CURRENT", "PROTECTION", "THERMAL")}
    for row in rows:
        if set(row) != set(COLUMNS):
            raise ValueError("Wrong physical measurement schema/CSV columns")
        key = row["metric_id"].strip()
        if key not in expected or key in observed:
            raise ValueError("Missing, duplicate or unknown metric: " + key)
        _, domain, unit, condition = expected[key]
        if (row["domain"] != domain or row["unit"] != unit or
                row["condition_id"] != condition):
            raise ValueError("Physical unit/domain/condition mismatch: " + key)
        if not row["requirement_ref"].strip():
            raise ValueError("Physical requirement trace missing: " + key)
        state = row["capture_status"].strip()
        value = row["measured_value"].strip()
        if state not in ("OPEN", "CAPTURED"):
            raise ValueError("No automated physical PASS/FAIL approval: " + key)
        if state == "OPEN":
            if value or any(row[col].strip() for col in (
                    "raw_trace_ref", "board_revision", "board_serial",
                    "firmware_sha", "instrument_id", "measured_at_utc",
                    "acceptance_criteria_ref")):
                raise ValueError("OPEN measurement contains unreviewed fabricated/partial data: " + key)
        else:
            mandatory = ("measured_value", "raw_trace_ref", "board_revision",
                         "board_serial", "firmware_sha", "instrument_id",
                         "measured_at_utc")
            if any(not row[col].strip() for col in mandatory):
                raise ValueError("Physical CAPTURED row missing raw provenance: " + key)
            if not re.fullmatch(r"[0-9a-fA-F]{40}", row["firmware_sha"].strip()):
                raise ValueError("Real firmware commit SHA must be explicit: " + key)
            trace = row["raw_trace_ref"].strip().lower()
            if trace.startswith(("qemu:", "sim:", "mock:", "unit:", "fixture:")):
                raise ValueError("Simulated waveform cannot be physical trace: " + key)
            timestamp = row["measured_at_utc"].strip()
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("Invalid actual UTC measurement timestamp: " + key) from exc
            if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
                raise ValueError("Timestamp must be timezone-aware UTC: " + key)
            if unit not in TEXT_UNITS:
                try:
                    x = float(value)
                except ValueError as exc:
                    raise ValueError("Non-numeric physical measurement: " + key) from exc
                if not math.isfinite(x):
                    raise ValueError("Non-finite physical measurement: " + key)
            counts[domain]["captured"] += 1
        counts[domain]["total"] += 1
        observed[key] = state
    missing = sorted(set(expected) - set(observed))
    if missing:
        raise ValueError("Physical metric coverage incomplete: " + ",".join(missing))
    captured = sum(x["captured"] for x in counts.values())
    return {
        "schema_valid": True,
        "physical_evidence_state": (
            "OPEN_NO_BOARD_MEASUREMENTS" if captured == 0 else
            "CAPTURED_REQUIRES_ENGINEERING_REVIEW"
        ),
        "hardware_qualified": False,
        "captured_rows": captured,
        "total_required_rows": len(REQUIRED),
        "domain_coverage": counts,
        "numeric_qemu_vs_47v_hardware_comparison": "NOT_PERMITTED_DIFFERENT_POWER_AND_MOTOR_MODEL",
        "physical_approval": "OPEN_REQUIRES_LAB_REPORT_AND_OWNER_SIGNOFF",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    with args.csv.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != list(COLUMNS):
            raise ValueError("Physical CSV header differs from strict schema")
        verdict = evaluate_hardware_rows(list(reader))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(verdict, indent=2) + "\n")
    print("PASS_E62_HARDWARE_EVIDENCE_SCHEMA_VALIDATION_ONLY " +
          json.dumps(verdict, sort_keys=True))


if __name__ == "__main__":
    main()
