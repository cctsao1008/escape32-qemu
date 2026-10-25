"""Archive bytes and current-source fingerprint are distinct claims."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from tools.ci.audit_historical_pinned import FILES,audit

def sha(data):
    return hashlib.sha256(data).hexdigest()

class HistoricalPinnedIntegrityUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        base=self.root/'baseline/e62-g13b3'
        base.mkdir(parents=True)
        self.binary_bytes={p:(b'G13B3-'+p.encode()) for p in FILES}
        for p,data in self.binary_bytes.items():
            file=base/p;file.parent.mkdir(parents=True,exist_ok=True)
            file.write_bytes(data)
        src=self.root/'machine/am13e23019.c'
        src.parent.mkdir(parents=True)
        src.write_bytes(b'original-g13b3-model')
        manifest={
            'schema':'e62-g13b3-paired-binary-baseline.v1',
            'id':'E62-G13B3-SIM_ONLY-UBUNTU24-X86_64-v1',
            'files':{p:{'sha256':sha(data),'size_bytes':len(data)}
                     for p,data in self.binary_bytes.items()},
            'qemu':{'source_tree_sha256':
                    {'machine/am13e23019.c':sha(src.read_bytes())}}
        }
        (base/'manifest.json').write_text(json.dumps(manifest))
        (base/'SHA256SUMS').write_text(
            ''.join(f'{sha(self.binary_bytes[p])}  {p}\n' for p in FILES))
        self.elfsha=sha(self.binary_bytes[FILES[0]])

    def check(self):
        return audit(self.root,expected_elf=self.elfsha)

    def test_archive_still_intact(self):
        d=self.check()
        self.assertEqual(d['status'],'PASS_HISTORICAL_BYTES_INTEGRITY_ONLY')
        self.assertEqual(d['issues'],[])
        self.assertFalse(d['current_source_drift'])

    def test_current_machine_drift_cannot_be_called_source_qualified(self):
        (self.root/'machine/am13e23019.c').write_bytes(b'new model')
        d=self.check()
        self.assertEqual(d['status'],'PASS_HISTORICAL_BYTES_INTEGRITY_ONLY')
        self.assertTrue(d['current_source_drift'])
        self.assertFalse(d['current_source_pair_qualified'])
        self.assertIn('KNOWN_FAIL',d['original_g13b3m_rotor_stability'])

    def test_modified_archive_binary_must_fail(self):
        (self.root/'baseline/e62-g13b3'/FILES[1]).write_bytes(b'tampered')
        d=self.check()
        self.assertEqual(d['status'],'FAIL_ARCHIVE_INTEGRITY')
        self.assertTrue(any('checksum_mismatch' in e for e in d['issues']))

    def test_modified_archive_ledger_must_fail(self):
        (self.root/'baseline/e62-g13b3/SHA256SUMS').write_text('bad\n')
        self.assertIn('archive_SHA256SUMS_ledger_mismatch',self.check()['issues'])

    def test_missing_binary_must_fail(self):
        (self.root/'baseline/e62-g13b3'/FILES[2]).unlink()
        self.assertTrue(self.check()['issues'])
