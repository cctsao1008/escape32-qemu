"""Fail-closed host-only regression for original Guest functional PWM journal.

Fixtures are QEMU-history ABI snapshots, NOT measured QEMU firmware runs.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_native_pwm_history import fixture
from tools.functional_pwm_clocked_trace import FunctionalClockedPWMTrace


BASELINE = [(0,4,0,0,0,0)]
PROGRESSED = BASELINE + [
    (100,5,0,21,0,0),
    (250,1,21,20,25,0),
    (400,1,20,16,40,0),
    (600,1,16,0,60,0),
    (1000,2,0,21,0,1),
]


def reader(items):
    return fixture(items).__getitem__


class ClockedOriginalGuestFunctionalHistory(unittest.TestCase):
    def test_callback_timestamp_and_zero_with_equal_guest_systick(self):
        c=FunctionalClockedPWMTrace()
        c.attach(reader(BASELINE))
        c.poll(reader(PROGRESSED),wfi=1,guest_elapsed_ns=62_500,
               guest_step=2,guest_serviced=1)
        # Multiple original Guest WFI can share a 16kHz SysTick.
        c.poll(reader(PROGRESSED),wfi=2,guest_elapsed_ns=62_500,
               guest_step=2,guest_serviced=1)
        r=c.report()
        self.assertEqual(r["status"],
                         "PASS_QEMU_CLOCKED_INTERNAL_PWM_HISTORY_ONLY")
        self.assertEqual(r["qemu_clocked_edge_callbacks"],3)
        self.assertEqual(r["original_pwm_zero_callbacks"],1)
        self.assertEqual(r["collected_events"],5)
        self.assertEqual(r["events"][1]["virtual_ns"],250)
        self.assertEqual(r["events"][1]["observed_guest_timg12_serviced"],1)
        self.assertFalse(r["original_guest_systick_vs_qemu_global_ns_aligned"])
        self.assertFalse(r["physical_mosfet_edges_qualified"])

    def test_wrong_wfi_order_must_halt_without_spoofed_callbacks(self):
        c=FunctionalClockedPWMTrace()
        c.attach(reader(BASELINE))
        c.poll(reader(PROGRESSED),wfi=2,guest_elapsed_ns=125_000,
               guest_step=2,guest_serviced=1)
        r=c.report()
        self.assertTrue(r["collector_halted"])
        self.assertEqual(r["collected_events"],0)
        self.assertIn("Nonconsecutive",r["collection_error"]["message"])

    def test_event_gap_from_overwritten_ring_fail_closed(self):
        c=FunctionalClockedPWMTrace()
        c.attach(reader(BASELINE))
        # The 128-event QEMU ring overwrites 12 events after attachment.
        over=BASELINE+[(10*i,7,0,0,0,0) for i in range(1,141)]
        c.poll(reader(over),wfi=1,guest_elapsed_ns=62_500,
               guest_step=1,guest_serviced=0)
        r=c.report()
        self.assertEqual(r["missed_ring_events"],12)
        self.assertEqual(r["status"],"OPEN_OR_FAIL_QEMU_CLOCKED_PWM_HISTORY")

    def test_internal_both_gate_high_is_recorded_not_accepted(self):
        c=FunctionalClockedPWMTrace()
        c.attach(reader(BASELINE))
        bad=BASELINE+[(100,1,0,3,10,0),
                      (1000,2,3,0,0,1)]
        c.poll(reader(bad),wfi=1,guest_elapsed_ns=62_500,
               guest_step=2,guest_serviced=1)
        r=c.report()
        self.assertGreater(r["unsafe_internal_both_gates_high_masks"],0)
        self.assertEqual(r["status"],"OPEN_OR_FAIL_QEMU_CLOCKED_PWM_HISTORY")

    def test_storage_bound_never_drops_old_original_events(self):
        c=FunctionalClockedPWMTrace(max_events=128)
        c.attach(reader(BASELINE))
        first=BASELINE+[(i*10,7,0,0,0,0) for i in range(1,101)]
        c.poll(reader(first),wfi=1,guest_elapsed_ns=62_500,
               guest_step=1,guest_serviced=0)
        second=first+[(i*10,7,0,0,0,0) for i in range(101,151)]
        c.poll(reader(second),wfi=2,guest_elapsed_ns=125_000,
               guest_step=1,guest_serviced=0)
        r=c.report()
        self.assertEqual(r["collected_events"],100)
        self.assertTrue(r["collector_halted"])
        self.assertIn("storage",r["collection_error"]["message"])
        self.assertEqual(r["status"],"OPEN_OR_FAIL_QEMU_CLOCKED_PWM_HISTORY")

    def test_model_invalid_counter_cannot_pass(self):
        c=FunctionalClockedPWMTrace()
        c.attach(reader(BASELINE))
        d=fixture(PROGRESSED)
        from tools.native_pwm_history import BASE
        d[BASE+0x40]=1
        c.poll(d.__getitem__,wfi=1,guest_elapsed_ns=62_500,
               guest_step=2,guest_serviced=1)
        r=c.report()
        self.assertEqual(r["qemu_pwm_invalid_model_events_since_attach"],1)
        self.assertEqual(r["status"],"OPEN_OR_FAIL_QEMU_CLOCKED_PWM_HISTORY")


if __name__=="__main__":
    unittest.main()
