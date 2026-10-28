#!/usr/bin/env python3
"""Unit checks that historical pairing is never waived or republished."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.e62_pinned_source_drift_report import diff,calculate,ROOT
from tools.e62_pinned_baseline import SOURCE_FILES

class HistoricalSourceDriftTest(unittest.TestCase):
    def test_identical_sources_all_match(self):
        rows=diff({"a":"abc"},{"a":"abc"})
        self.assertEqual(rows[0]["status"],"MATCH")
    def test_changed_source_remains_explicit_drift(self):
        rows=diff({"a":"abc"},{"a":"def"})
        self.assertEqual(rows[0]["status"],"SOURCE_SHA256_DRIFT")
    def test_missing_source_not_silently_removed(self):
        rows=diff({"a":"abc"},{})
        self.assertEqual(rows[0]["status"],"SOURCE_FILE_MISSING")
    def test_unpinned_file_not_silently_added(self):
        rows=diff({"a":"abc"},{"a":"abc","b":"xyz"})
        self.assertEqual(rows[1]["status"],"UNPINNED_NEW_FILE")
    def test_actual_manifest_readonly_diagnosis(self):
        manifest=ROOT/"baseline/e62-g13b3/manifest.json"
        before=manifest.read_bytes()
        r=calculate(ROOT)
        self.assertEqual(manifest.read_bytes(),before)
        self.assertEqual(r["source_file_count"],len(SOURCE_FILES))
        self.assertFalse(r["archived_binary_pair_republished"])
        self.assertFalse(r["archive_manifest_modified"])
        self.assertFalse(r["binary_byte_integrity_checked_by_this_tool"])
        self.assertEqual(r["strict_original_verifier_passing"],
                         r["drift_count"]==0)

if __name__=="__main__":
    unittest.main(verbosity=2)
