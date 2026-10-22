#!/usr/bin/env python3
"""Schema-only tests: entirely synthetic intake never establishes board PASS."""
import csv
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.e62_hardware_evidence import REQUIRED, COLUMNS, evaluate_hardware_rows


def blank():
    return [{name: (id if name == "metric_id" else
                    domain if name == "domain" else
                    unit if name == "unit" else
                    condition if name == "condition_id" else
                    "Engineering source / TBD" if name == "requirement_ref" else
                    "OPEN" if name == "capture_status" else "")
             for name in COLUMNS}
            for id, domain, unit, condition in REQUIRED]


def captured(row):
    row["capture_status"] = "CAPTURED"
    row["measured_value"] = "1" if row["unit"] not in ("text", "sequence") else "U->V"
    row["raw_trace_ref"] = "lab://E62/trace/00001"
    row["board_revision"] = "EVT"
    row["board_serial"] = "UNQUALIFIED_FIXTURE"
    row["firmware_sha"] = "1234567890abcdef1234567890abcdef12345678"
    row["instrument_id"] = "SCOPE_CAL_001"
    row["measured_at_utc"] = "2026-10-23T09:00:00Z"


class HardwareEvidenceIntake(unittest.TestCase):
    def test_empty_hardware_is_open_not_a_pass(self):
        v = evaluate_hardware_rows(blank())
        self.assertFalse(v["hardware_qualified"])
        self.assertEqual(v["captured_rows"], 0)
        self.assertEqual(v["physical_evidence_state"], "OPEN_NO_BOARD_MEASUREMENTS")
        self.assertEqual(set(v["domain_coverage"]),
                         {"PWM", "CURRENT", "PROTECTION", "THERMAL"})

    def test_no_qemu_hardware_trace(self):
        rows = blank()
        captured(rows[0])
        rows[0]["raw_trace_ref"] = "qemu://fake_capture"
        with self.assertRaisesRegex(ValueError, "Simulated waveform"):
            evaluate_hardware_rows(rows)

    def test_real_captured_still_requires_review(self):
        rows = blank()
        captured(rows[0])
        v = evaluate_hardware_rows(rows)
        self.assertEqual(v["captured_rows"], 1)
        self.assertFalse(v["hardware_qualified"])
        self.assertEqual(v["physical_approval"],
                         "OPEN_REQUIRES_LAB_REPORT_AND_OWNER_SIGNOFF")

    def test_fail_on_missing_hardware_identity(self):
        rows = blank()
        captured(rows[0])
        rows[0]["board_serial"] = ""
        with self.assertRaisesRegex(ValueError, "provenance"):
            evaluate_hardware_rows(rows)

    def test_fail_on_fake_numeric_nan(self):
        rows = blank()
        captured(rows[1])
        rows[1]["measured_value"] = "nan"
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            evaluate_hardware_rows(rows)

    def test_fail_on_missing_or_duplicate_metrics(self):
        rows = blank()
        with self.assertRaisesRegex(ValueError, "coverage"):
            evaluate_hardware_rows(rows[:-1])
        rows.append(rows[0].copy())
        with self.assertRaisesRegex(ValueError, "duplicate"):
            evaluate_hardware_rows(rows)

    def test_no_unbacked_pass_or_open_with_numbers(self):
        rows = blank()
        rows[0]["capture_status"] = "PASS"
        with self.assertRaisesRegex(ValueError, "approval"):
            evaluate_hardware_rows(rows)
        rows = blank()
        rows[0]["measured_value"] = "5"
        with self.assertRaisesRegex(ValueError, "unreviewed"):
            evaluate_hardware_rows(rows)


if __name__ == "__main__":
    unittest.main(verbosity=2)
