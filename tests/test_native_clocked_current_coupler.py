"""Actual QEMU-clocked AQ/DB journal -> current-continuous physics.

These are controlled model boundary tests, not evidence of original
Guest closed-loop/real motor performance.
"""
import unittest
from types import SimpleNamespace

from tools.native_clocked_current_coupler import (
    NativeClockedCurrentCoupler, _topology, _raw_gate_enabled,
)


def event(seq, ns, old, new, *, enabled=True):
    return {
        "sequence":seq,"virtual_ns":ns,"old_mask":old,"new_mask":new,
        "raw_pb13":int(enabled),"pb13_doe":enabled,"gpio_powered":True,
        "pb13_pinmux_valid":True,"raw_trip_ost_bits":0,
        "internal_level_evaluator_valid":True,
    }


def journal(events=None, *, last_mask=0, errors=None, gaps=None):
    return SimpleNamespace(
        attached=True,halted=False,attach_total=0,
        last_mask=last_mask,
        events=events or [],errors=errors or [],gaps=gaps or [],
        invalid_since_attach=0,polls=[{"wfi":1}]
    )


class OriginalClockedCurrentCouplerTests(unittest.TestCase):
    def test_actual_execution_edges_drive_current_and_bemf(self):
        c=NativeClockedCurrentCoupler(max_substep_ns=1000)
        c.attach(journal(),virtual_ns=0,gate_qualified=True)
        e=[event(0,1000,0,9),event(1,3000,9,0)]
        h=journal(e,last_mask=0)
        sample=c.consume(h,guest_wfi=1,observed_virtual_ns=4000)
        self.assertEqual(c.records_consumed,2)
        self.assertEqual(c.total_integrated_ns,4000)
        self.assertEqual(c.event_topology_changes,2)
        self.assertTrue(all(isinstance(i,float) for i in sample.phase_currents_a))
        memory={}
        words=c.inject_bemf(memory.__getitem__,memory.__setitem__)
        self.assertEqual(len(words),3)
        self.assertEqual(c.analog_samples,1)
        self.assertFalse(c.evidence()["calibrated_motor"])

    def test_source_mask_shootthrough_fails_closed(self):
        c=NativeClockedCurrentCoupler()
        c.attach(journal(),virtual_ns=0,gate_qualified=True)
        with self.assertRaisesRegex(ValueError,"shoot-through"):
            c.consume(journal([event(0,1000,0,3)],last_mask=3),
                      guest_wfi=1,observed_virtual_ns=1500)

    def test_lost_source_edge_never_interpolates(self):
        c=NativeClockedCurrentCoupler()
        c.attach(journal(),virtual_ns=0,gate_qualified=True)
        with self.assertRaisesRegex(ValueError,"sequence gap"):
            c.consume(journal([event(1,1000,0,9)],last_mask=9),
                      guest_wfi=1,observed_virtual_ns=1500)

    def test_ring_overrun_fails_even_with_later_events(self):
        c=NativeClockedCurrentCoupler()
        c.attach(journal(),virtual_ns=0,gate_qualified=True)
        with self.assertRaisesRegex(ValueError,"Missing/invalid"):
            c.consume(journal([event(0,1000,0,9)],last_mask=9,
                              gaps=[{"missing_events":1}]),
                      guest_wfi=1,observed_virtual_ns=1500)

    def test_unclocked_pwm_plan_not_accepted_as_event_history(self):
        c=NativeClockedCurrentCoupler()
        c.attach(journal(),virtual_ns=0,gate_qualified=True)
        self.assertNotIn("QEMU_ACTIVE_AQ_DB_ONE_CARRIER_MODEL_RECONSTRUCTION",
                         c.source)
        with self.assertRaisesRegex(ValueError,"No verified actual PWM"):
            c.inject_bemf(lambda _:0,lambda _a,_v:None)

    def test_gate_and_trip_cannot_energize_bridge(self):
        h=event(0,0,0,9,enabled=False)
        self.assertFalse(_raw_gate_enabled(h))
        self.assertEqual(_topology(9,enabled=False).legs,("Z","Z","Z"))
        h=event(0,0,0,9);h["raw_trip_ost_bits"]=2
        self.assertFalse(_raw_gate_enabled(h))

    def test_no_physics_step_across_unobserved_guest_gap(self):
        c=NativeClockedCurrentCoupler(max_wfi_gap_ns=10000)
        c.attach(journal(),virtual_ns=0,gate_qualified=True)
        with self.assertRaisesRegex(ValueError,"Unbounded"):
            c.consume(journal([event(0,1000,0,9)],last_mask=9),
                      guest_wfi=1,observed_virtual_ns=20000)

    def test_atomic_source_snapshot_clock_reader(self):
        from tools.native_pwm_switching_plan import SWITCH_BASE
        read=lambda addr:{SWITCH_BASE+0x24:42,SWITCH_BASE+0x28:1}[addr]
        self.assertEqual(
            NativeClockedCurrentCoupler.virtual_time_at_guest_wfi(read),
            (1<<32)|42)
