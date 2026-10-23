#!/usr/bin/env python3
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_closed_loop_audit import (
    NativeClosedLoopAudit, ORIGINAL_REL17_ROUTE, REL17_COMMUTATION_SEQUENCE
)


def snap(t, *, cap=0, c1=0, rej=0, sch=1, srv=0, step=1, code=5,
         pwm=(0,0,0,6250,620,0), rpm=123, armed=True, pending=0):
    return dict(ecap_ticks=t, cap1_ticks=c1, captured=cap, rejected=rej,
                scheduled=sch, serviced=srv, step=step, selected_code=code,
                pwm_high=pwm, pwm_period=6251, gate_trip_qualified=True,
                rpm=rpm, armed=armed, pending_code=pending)


class TestNativeClosedLoopAudit(unittest.TestCase):
    def test_source_derived_original_rel17_six_step_route(self):
        # Check against the actual six immutable words in Rel17
        # src/commutation.h, not the previous incorrect audit table.
        self.assertEqual(
            REL17_COMMUTATION_SEQUENCE,
            (0x175, 0xd9, 0x1ab, 0x72, 0x1de, 0xac))
        self.assertEqual(
            ORIGINAL_REL17_ROUTE,
            (None, (5, (2, 1)), (3, (0, 1)), (6, (0, 2)),
             (1, (1, 2)), (7, (1, 0)), (2, (2, 0))))
        a = NativeClosedLoopAudit()
        a.ingest(**snap(100, step=3, code=6,
                        pwm=(620, 0, 0, 0, 0, 6250)))
        with self.assertRaisesRegex(
                AssertionError, "Armed original BEMF phase differs"):
            a.ingest(**snap(200, step=3, code=7,
                            pwm=(620, 0, 0, 0, 0, 6250)))

    def test_six_actual_feedback_orderings(self):
        a = NativeClosedLoopAudit()
        phases = [
            (0,0,0,6250,620,0), (620,0,0,6250,0,0),
            (620,0,0,0,0,6250), (0,0,620,0,0,6250),
            (0,6250,620,0,0,0), (0,6250,0,0,620,0)]
        codes = [5,3,6,1,7,2]
        t = 100
        a.ingest(**snap(t,pwm=phases[0]))
        for k in range(6):
            t += 100
            a.ingest(**snap(t,cap=k+1,c1=t-30,sch=k+2,srv=k,
                            step=k+1,code=codes[k],pwm=phases[k]))
            t += 100
            a.ingest(**snap(t,cap=k+1,c1=t-130,sch=k+2,srv=k+1,
                            step=(k+1)%6+1,code=codes[(k+1)%6],
                            pwm=phases[(k+1)%6]))
        self.assertTrue(a.qualified)
        self.assertEqual(len(a.sectors), 6)

    def test_native_carrier_zero_must_publish_bemf_after_timer(self):
        a=NativeClosedLoopAudit()
        before=(0,0,0,6250,620,0)
        after=(620,0,0,6250,0,0)
        a.ingest(**snap(100,pwm=before))
        a.ingest(**snap(200,cap=1,c1=170,sch=2,pwm=before))
        # TIMG12 ran and original nextstep staged AQ, but the
        # original BEMF phase has not yet been published by PWM ZERO.
        a.ingest(**snap(300,cap=1,c1=170,sch=2,srv=1,step=2,
                        code=0,armed=False,pending=3,pwm=before))
        self.assertEqual(len(a.sectors),0)
        self.assertIsNotNone(a.pending)
        # Firmware-controlled MCPWM carrier ZERO publishes new mux,
        # physically changed high/low vector, rearmed comparator.
        a.ingest(**snap(400,cap=1,c1=170,sch=2,srv=1,step=2,
                        code=3,armed=True,pending=0,pwm=after))
        self.assertEqual(len(a.sectors),1)
        self.assertIsNone(a.pending)
    def test_unpublished_bemf_without_pending_rejected(self):
        a=NativeClosedLoopAudit()
        with self.assertRaisesRegex(AssertionError,"code0"):
            a.ingest(**snap(100,code=0,armed=False,pending=0))
    def test_wrong_measured_guest_vector_rejected(self):
        a=NativeClosedLoopAudit()
        a.ingest(**snap(100))
        a.ingest(**snap(200,cap=1,c1=170,sch=2))
        with self.assertRaisesRegex(AssertionError,"sixstep vector"):
            a.ingest(**snap(300,cap=1,c1=170,sch=2,srv=1,step=2,
                            code=3,pwm=(620,0,0,0,0,6250)))

    def test_early_reject_is_not_sector(self):
        a = NativeClosedLoopAudit()
        a.ingest(**snap(100))
        a.ingest(**snap(200,cap=1,c1=150,rej=1))
        self.assertEqual(a.early_rejections, 1)
        self.assertEqual(len(a.sectors), 0)

    def test_source_owned_bemf_rejection_window_reset_after_native_timg12(self):
        # Pinned original motor_bemf.c resets rejected_events per interval
        # after a genuine nextstep re-arms capture, not on Host command.
        a = NativeClosedLoopAudit(required_sectors=12)
        first = (0,0,0,6250,620,0)
        second = (620,0,0,6250,0,0)
        a.ingest(**snap(100, pwm=first))
        # Early CAP1 rejected by original Rel17, not counted as sector.
        a.ingest(**snap(200,cap=1,c1=175,rej=1,sch=1,pwm=first))
        self.assertEqual(a.early_rejections, 1)
        self.assertEqual(len(a.sectors), 0)
        # A NEW CAP1 accepted and scheduled, with rejection still 1.
        a.ingest(**snap(300,cap=2,c1=270,rej=1,sch=2,pwm=first))
        self.assertIsNotNone(a.pending)
        # Original TIMG12 moves step and source-owned interval rearm
        # clears rejected_events=0, while old rejected CAP1 stays uncredited.
        a.ingest(**snap(400,cap=2,c1=270,rej=0,sch=2,srv=1,
                        step=2,code=3,pwm=second))
        self.assertEqual(a.original_rejection_window_resets, 1)
        self.assertEqual(a.early_rejections, 1)
        self.assertEqual(len(a.sectors), 1)
        self.assertFalse(a.qualified)

    def test_native_deferred_carrier_zero_rejection_reset(self):
        a = NativeClosedLoopAudit(required_sectors=12)
        first = (0,0,0,6250,620,0)
        second = (620,0,0,6250,0,0)
        a.ingest(**snap(100, pwm=first))
        a.ingest(**snap(200, cap=1, c1=170, rej=1, sch=1, pwm=first))
        a.ingest(**snap(300, cap=2, c1=270, rej=1, sch=2, pwm=first))
        # Original TIMG12 advances Guest step, but carrier ZERO has not
        # consumed the pending AQ image and the rejection window stays 1.
        a.ingest(**snap(400, cap=2, c1=270, rej=1, sch=2, srv=1,
                        step=2, code=0, armed=False, pending=3, pwm=first))
        self.assertIsNotNone(a.pending)
        self.assertEqual(len(a.sectors), 0)
        # An additional genuine WFI can occur in the staged window.
        a.ingest(**snap(450, cap=2, c1=270, rej=1, sch=2, srv=1,
                        step=2, code=0, armed=False, pending=3, pwm=first))
        # Only the original MCPWM ZERO publishes the next COMP+PWM
        # phase and resets rejected_events in interval_select().
        a.ingest(**snap(500, cap=2, c1=270, rej=0, sch=2, srv=1,
                        step=2, code=3, armed=True, pending=0, pwm=second))
        self.assertEqual(a.original_rejection_window_resets, 1)
        self.assertEqual(a.early_rejections, 1)
        self.assertEqual(len(a.sectors), 1)

    def test_deferred_reset_requires_same_original_timer_and_phase(self):
        first = (0,0,0,6250,620,0)
        for change in ("new_capture", "wrong_code", "not_armed",
                       "missing_pending", "no_original_timer"):
            a = NativeClosedLoopAudit(required_sectors=12)
            a.ingest(**snap(100, pwm=first))
            a.ingest(**snap(200, cap=1, c1=170, rej=1, sch=1, pwm=first))
            a.ingest(**snap(300, cap=2, c1=270, rej=1, sch=2, pwm=first))
            a.ingest(**snap(400, cap=2, c1=270, rej=1, sch=2, srv=1,
                            step=2, code=0, armed=False, pending=3, pwm=first))
            after = snap(500, cap=2, c1=270, rej=0, sch=2, srv=1,
                         step=2, code=3, armed=True, pending=0,
                         pwm=(620,0,0,6250,0,0))
            if change == "new_capture":
                after["captured"] = 3
            elif change == "wrong_code":
                after["selected_code"] = 5
            elif change == "not_armed":
                after["armed"] = False
            elif change == "missing_pending":
                a.pending = None
            else:
                a.pending["service_tick"] = None
            with self.subTest(change=change):
                with self.assertRaises(AssertionError):
                    a.ingest(**after)
                self.assertEqual(a.original_rejection_window_resets, 0)

    def test_bemf_rejection_reset_without_native_step_stays_rejected(self):
        a=NativeClosedLoopAudit(required_sectors=12)
        a.ingest(**snap(100))
        a.ingest(**snap(200,cap=1,c1=175,rej=1))
        with self.assertRaisesRegex(AssertionError, "WITHOUT"):
            a.ingest(**snap(300,cap=1,c1=175,rej=0))
        self.assertEqual(len(a.sectors), 0)

    def test_bemf_rejection_reset_with_fake_step_or_missing_service_fails(self):
        a=NativeClosedLoopAudit(required_sectors=12)
        a.ingest(**snap(100))
        a.ingest(**snap(200,cap=1,c1=175,rej=1))
        a.ingest(**snap(300,cap=2,c1=275,rej=1,sch=2))
        with self.assertRaisesRegex(AssertionError, "WITHOUT"):
            a.ingest(**snap(400,cap=2,c1=275,rej=0,sch=2,srv=0,
                            step=2,code=3))
        self.assertEqual(len(a.sectors), 0)

    def test_isr_but_sink_only_is_not_powered_sector(self):
        a = NativeClosedLoopAudit()
        a.ingest(**snap(100))
        a.ingest(**snap(200,cap=1,c1=160,sch=2))
        a.ingest(**snap(300,cap=1,c1=160,sch=2,srv=1,
                        step=2,code=3,pwm=(0,0,0,6250,0,0)))
        self.assertFalse(a.qualified)
        self.assertEqual(len(a.sectors), 0)
        self.assertEqual(a.unpowered_native_timg12_steps,0)

    def test_unpowered_startup_step_does_not_poison_later_feedback(self):
        a = NativeClosedLoopAudit()
        a.ingest(**snap(100, pwm=(0,0,0,6220,0,0)))
        a.ingest(**snap(200,cap=1,c1=150,sch=2,
                        pwm=(0,0,0,6220,0,0)))
        a.ingest(**snap(300,cap=1,c1=150,sch=2,srv=1,
                        step=2,code=3,pwm=(0,0,0,6220,0,0)))
        self.assertIsNone(a.pending)
        self.assertEqual(a.unpowered_native_timg12_steps,1)
        self.assertEqual(len(a.sectors),0)
        # On a later power stage, the verifier can accept NEW
        # physical evidence without crediting the early invalid one.
        a.ingest(**snap(400,cap=1,c1=150,sch=2,srv=1,
                        step=2,code=3,pwm=(620,0,0,6220,0,0)))
        a.ingest(**snap(500,cap=2,c1=470,sch=3,srv=1,
                        step=2,code=3,pwm=(620,0,0,6220,0,0)))
        self.assertIsNotNone(a.pending)

    def test_no_cap1_change_rejected(self):
        a = NativeClosedLoopAudit()
        a.ingest(**snap(100))
        with self.assertRaisesRegex(AssertionError, "CAP1"):
            a.ingest(**snap(200,cap=1,c1=0,sch=2))

    def test_guest_event_skip_rejected(self):
        a = NativeClosedLoopAudit()
        a.ingest(**snap(100))
        with self.assertRaisesRegex(AssertionError, "Missed multiple"):
            a.ingest(**snap(200,cap=2,c1=160,sch=3))

    def test_timer_service_without_new_step_rejected(self):
        a = NativeClosedLoopAudit()
        a.ingest(**snap(100))
        a.ingest(**snap(200,cap=1,c1=160,sch=2))
        with self.assertRaisesRegex(AssertionError, "nextstep"):
            a.ingest(**snap(300,cap=1,c1=160,sch=2,srv=1))
if __name__ == "__main__":
    unittest.main(verbosity=2)
