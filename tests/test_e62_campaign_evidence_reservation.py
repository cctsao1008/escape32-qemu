"""Failure evidence must survive absent final JSON and concurrent attempts."""
import tempfile,threading,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from tools.e62_restart_rate_campaign import reserve_evidence
class EvidenceReservationTests(unittest.TestCase):
    def test_partial_outputs_are_not_discarded(self):
        for suffix in ('.command.json','.qemu.log','.stdout.log','.json'):
            with tempfile.TemporaryDirectory() as td:
                target=Path(td)/'failed.json';old=target.with_suffix(suffix);old.write_text('previous failed evidence')
                with self.assertRaises(ValueError):reserve_evidence(target)
                self.assertEqual(old.read_text(),'previous failed evidence')
                self.assertEqual(list(Path(td).iterdir()),[old])
    def test_literal_case_names_do_not_expand_glob_patterns(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'failed[0].json';old=target.with_suffix('.qemu.log');old.write_text('failure')
            with self.assertRaises(ValueError):reserve_evidence(target)
            self.assertEqual(old.read_text(),'failure')
    def test_failed_reservation_is_sticky(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'attempt.json';marker=reserve_evidence(target);before=marker.read_bytes()
            with self.assertRaises(ValueError):reserve_evidence(target)
            self.assertEqual(marker.read_bytes(),before)
    def test_only_one_concurrent_attempt_can_own_a_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'case.json';barrier=threading.Barrier(2)
            def attempt():
                barrier.wait()
                try:reserve_evidence(target);return True
                except ValueError:return False
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:attempt(),range(2)))
            self.assertEqual(sorted(results),[False,True])
    def test_different_case_prefix_is_not_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            a=reserve_evidence(Path(td)/'first.json');b=reserve_evidence(Path(td)/'second.json');self.assertNotEqual(a,b)
    def test_campaign_index_is_reserved_before_results_exist(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'execution-result.json';reserve_evidence(target)
            with self.assertRaises(ValueError):reserve_evidence(target)
if __name__=='__main__':unittest.main()
