"""UNIT_ONLY tests: physical Guest read-only BEMF decision ring decoding."""
import unittest
from tools.e62_issue5_bemf_diag import snapshot, snapshot_first, decode_entry


class RingTests(unittest.TestCase):
    def test_accept_and_reject_preserve_prior_ival(self):
        accepted = decode_entry([100, 770, 10000, 300, 0, 1], 4)
        rejected = decode_entry([101, 300, 10000, 0, 1, 2], 5)
        self.assertEqual(accepted["decision"], "ACCEPTED")
        self.assertEqual(rejected["decision"], "REJECTED_EARLY")
        self.assertEqual(rejected["original_early_threshold_us"], 5000)

    def test_wrap_and_overwritten(self):
        mem = {0x100: 66}
        for seq in range(2, 66):
            address = 0x1000 + (seq % 64) * 24
            for i, v in enumerate([seq, seq * 2, 10000, 0, 0, 2]):
                mem[address + 4 * i] = v
        result = snapshot(mem.__getitem__, 0x100, 0x1000)
        self.assertEqual((result["entries"][0]["seq"], result["entries"][-1]["seq"]), (2, 65))
        self.assertTrue(result["overwritten"])

    def test_persistent_first_history_survives_ring_wrap(self):
        mem = {0x100: 99}
        for seq in range(64):
            addr = 0x2000 + seq * 24
            for i, value in enumerate([seq, 400+seq, 10000, 0, 1, 2]):
                mem[addr + i*4] = value
        result = snapshot_first(mem.__getitem__, 0x100, 0x2000)
        self.assertEqual(len(result["entries"]), 64)
        self.assertTrue(result["first_history_capped"])
        self.assertEqual(result["entries"][0]["capture_us"], 400)
        self.assertEqual(result["entries"][63]["capture_us"], 463)

    def test_frozen_first_array_allows_growing_count_but_not_reset(self):
        def reader(counts):
            it=iter(counts)
            def read(addr):
                if addr==0x100:return next(it)
                return [10,500,10000,0,0,2][((addr-0x2000)//4)%6]
            return read
        r=snapshot_first(reader([64,67]),0x100,0x2000)
        self.assertEqual(r['snapshot_safety'],'IMMUTABLE_FIRST_ARRAY')
        self.assertEqual(len(r['entries']),64)
        with self.assertRaises(RuntimeError):snapshot_first(reader([64,1]),0x100,0x2000)
        with self.assertRaises(RuntimeError):snapshot_first(reader([63,64]),0x100,0x2000)

    def test_missing_first_history_word_fails(self):
        mem = {0x100: 1}
        with self.assertRaises(KeyError):
            snapshot_first(mem.__getitem__, 0x100, 0x2000)

    def test_invalid_decision_fails(self):
        with self.assertRaises(ValueError):
            decode_entry([0, 0, 0, 0, 0, 4], 0)

    def test_missing_word_fails(self):
        with self.assertRaises(ValueError):
            decode_entry([0], 0)

    def test_mutating_counter_fails(self):
        counters = iter([1, 2])
        def read(address):
            if address == 0x100:
                return next(counters)
            return [10, 500, 10000, 0, 0, 2][(address - 0x1000) // 4]
        with self.assertRaises(RuntimeError):
            snapshot(read, 0x100, 0x1000)


if __name__ == "__main__":
    unittest.main()
