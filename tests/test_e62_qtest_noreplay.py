import unittest
from tools.ci.prepare_qtest_noreplay import patch,OLD,NEW


class QtestTransportTests(unittest.TestCase):
    def test_exact_source_guard_idempotence_and_no_other_changes(self):
        before='prefix\n'+OLD+'\nsuffix\n';after=patch(before)
        self.assertEqual(after,'prefix\n'+NEW+'\nsuffix\n')
        self.assertEqual(patch(after),after)

    def test_absent_or_duplicate_anchor_rejected(self):
        for text in ('unexpected upstream',OLD+'\n'+OLD):
            with self.assertRaises(ValueError):patch(text)


if __name__=='__main__':unittest.main()
