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
                    {'machine/am13e23019.c':sha(src.read_bytes())},
                    'upstream_revision':'44f28df24767cf9dca1ddc9b23157737c4cbb645'},
            'guest':{
                'source_revision':'b0204670515d2de0b2480b52273038f1ee13d30a',
                'ti_sdk_revision':'b872469ceef18de5e39a1d3acb0821ec158b44c7'},
            'provenance':{'recorded_g13b3m_90ms_rotor':'FAIL_ORIGINAL_REVERSE_MOTION'}
        }
        (base/'manifest.json').write_text(json.dumps(manifest))
        (base/'SHA256SUMS').write_text(
            ''.join(f'{sha(self.binary_bytes[p])}  {p}\n' for p in FILES))
        self.original_archive_pins={
            rel:(sha(data),len(data)) for rel,data in self.binary_bytes.items()}

    def check(self):
        return audit(self.root,expected_archive=self.original_archive_pins)

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

    def test_synchronized_manifest_and_binary_replacement_fails(self):
        """Attack: rewrite QEMU, manifest digest, and SHA256SUMS together."""
        rel=FILES[1]
        base=self.root/'baseline/e62-g13b3'
        replacement=b'REPLACEMENT-QEMU-BYTES'
        (base/rel).write_bytes(replacement)
        manifest=json.loads((base/'manifest.json').read_text())
        manifest['files'][rel]={'sha256':sha(replacement),
                                 'size_bytes':len(replacement)}
        (base/'manifest.json').write_text(json.dumps(manifest))
        recorded={p:sha(replacement) if p==rel else sha(self.binary_bytes[p])
                  for p in FILES}
        (base/'SHA256SUMS').write_text(''.join(
            f'{recorded[p]}  {p}\n' for p in FILES))
        self.assertIn('archived_release_identity_mismatch:'+rel,
                      self.check()['issues'])

    def test_rotor_fail_provenance_cannot_be_rewritten(self):
        base=self.root/'baseline/e62-g13b3'
        manifest=json.loads((base/'manifest.json').read_text())
        manifest['provenance']['recorded_g13b3m_90ms_rotor']='PASS'
        (base/'manifest.json').write_text(json.dumps(manifest))
        self.assertIn('archive_rotor_known_failure_provenance_changed',
                      self.check()['issues'])

    def test_missing_binary_must_fail(self):
        (self.root/'baseline/e62-g13b3'/FILES[2]).unlink()
        self.assertTrue(self.check()['issues'])
