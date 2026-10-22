#!/usr/bin/env python3
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_closed_loop_audit import NativeClosedLoopAudit


def snap(t, *, cap=0, c1=0, rej=0, sch=1, srv=0, step=1, code=5,
         pwm=(0,0,0,6250,620,0), rpm=123):
    return dict(ecap_ticks=t, cap1_ticks=c1, captured=cap, rejected=rej,
                scheduled=sch, serviced=srv, step=step, selected_code=code,
                pwm_high=pwm, pwm_period=6251, gate_trip_qualified=True, rpm=rpm)


class TestNativeClosedLoopAudit(unittest.TestCase):
    def test_six_actual_feedback_orderings(self):
        a = NativeClosedLoopAudit()
        phases = [
            (0,0,0,6250,620,0), (620,0,0,6250,0,0),
            (620,0,0,0,0,6250), (0,0,620,0,0,6250),
            (0,6250,620,0,0,0), (0,6250,0,0,620,0)]
        codes = [5,3,7,2,6,1]
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

    def test_early_reject_is_not_sector(self):
        a = NativeClosedLoopAudit()
        a.ingest(**snap(100))
        a.ingest(**snap(200,cap=1,c1=150,rej=1))
        self.assertEqual(a.early_rejections, 1)
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
