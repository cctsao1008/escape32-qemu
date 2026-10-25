#!/usr/bin/env python3
"""Host-only trace format, safety and timestamp regressions (NO native PASS)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sitl_trace import SitlTraceRecorder, FORMAT


class TestSitlTrace(unittest.TestCase):
    def setUp(self):
        self.rec = SitlTraceRecorder(
            elf_sha256="a" * 64, initial_electrical_degrees=-30,
            required_sectors=12, required_integrated_ns=90_000_000)
        self.rec.set_gate_origin(self.frame(0, 0, 4294967000))

    @staticmethod
    def frame(index, elapsed_ns, tick):
        return NS(
            index=index,
            checkpoint=("native_gate_return" if index==0 else
                        f"native_sustained_wfi_{index}"),
            native_ecap_ticks=tick, elapsed_ns=elapsed_ns,
            total_integrated_ns=elapsed_ns,
            six_high_ticks=(0, 0, 0, 4136, 139, 3997),
            qualifier="SAMPLED_HOLD_INTERVAL",
        )

    @staticmethod
    def pwm():
        return NS(acceptable_for_plant=True, six_high_ticks=(0,0,0,4136,139,3997),
                  period_ticks=4136, gate_and_pads=True,
                  physical_ost2=False, physical_ost3=False)

    @staticmethod
    def plant():
        return NS(bemf_phase_v=(-.3,.1,.2),phase_currents_a=(.4,-.4,0),
                  mechanical_rpm=-133.0,electrical_rad=2.34)

    @staticmethod
    def guest():
        return dict(step=1,selected_code=5,armed=1,captured_events=1,
                    scheduled=1,serviced=1,rejected_events=0)

    @staticmethod
    def sector():
        # Tick timeline crosses uint32 rollover. Both events precede WFI 1.
        return NS(accepted_cap1_ticks=4294967010,
                  serviced_ecap_ticks=4294967020,
                  guest_step_before=1,guest_step_after=2)

    def observe(self, index=1, tick=4294967050, **changes):
        arguments=dict(
            visit=index,
            frame=self.frame(index, ((tick-4294967000)&0xffffffff)*5, tick),
            pwm=self.pwm(), plant=self.plant(), guest=self.guest(),
            analog=[2048, 2500, 1800], cap1_ticks=4294967010,
            sectors=[self.sector()])
        arguments.update(changes)
        self.rec.observe(**arguments)

    def test_native_wfi_trace_and_original_event_timing_wrap(self):
        self.observe()
        s=self.rec.document()["samples"][0]
        self.assertEqual(s["t_ns"],250)
        self.assertEqual(s["pwm_duties"][3],1.0)
        self.assertEqual(s["bemf_phase_v"],[-.3,.1,.2])
        self.assertEqual(s["motor_rpm"],-133)
        self.assertEqual([e["t_ns"] for e in self.rec.events],[50,100])
        self.observe(index=2,tick=100, sectors=[self.sector()])
        self.assertEqual(len(self.rec.events),2)
        self.assertEqual(self.rec.samples[-1]["t_ns"],
                         ((100-4294967000)&0xffffffff)*5)
        self.assertEqual(self.rec.meta["host_guest_register_writes"],False)

    def test_reject_out_of_order_wfi_and_invalid_pwm_without_rewriting(self):
        with self.assertRaisesRegex(ValueError,"consecutive"):
            self.observe(index=2)
        self.assertEqual(self.rec.samples,[])
        with self.assertRaisesRegex(ValueError,"Unqualified"):
            self.observe(pwm=NS(acceptable_for_plant=False,
                                six_high_ticks=(0,0,0,4136,139,3997),
                                period_ticks=4136))
        self.assertEqual(self.rec.samples,[])

    def test_reject_native_event_from_future(self):
        bad=self.sector()
        bad.serviced_ecap_ticks=4294967100
        with self.assertRaisesRegex(ValueError,"newer than WFI"):
            self.observe(sectors=[bad])
        self.assertEqual(len(self.rec.samples),0)

    def test_failure_writes_partial_trace_never_auto_pass(self):
        self.observe()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"trace.json"
            self.rec.write(path,error_type="RuntimeError")
            doc=json.loads(path.read_text())
            self.assertEqual(doc["format"],FORMAT)
            self.assertEqual(doc["capture_state"],"PARTIAL_EXCEPTION")
            self.assertIsNone(doc["native_result"])
            self.assertEqual(len(doc["samples"]),1)
            self.assertFalse(doc["metadata"]["host_guest_register_writes"])

    def test_native_milestone_is_not_extended_acceptance(self):
        self.observe()
        self.rec.finish(dict(qualified=True,
                             completed_feedback_powered_sectors=12,
                             plant_integrated_ns=90_000_000,
                             sim_only_rotor_motion={
                               "direction_continuity_qualified_sim_only":False,
                               "significant_direction_reversals":11}))
        d=self.rec.document()
        self.assertTrue(d["native_result"]["native_six_step_qualified"])
        self.assertFalse(d["native_result"]["direction_continuity_qualified_sim_only"])
        self.assertFalse(d["native_result"]["physical_motor_stability_qualified"])
        self.assertEqual(d["native_result"]["extended_strict_verdict"],
                         "NOT_EXECUTED_BY_TRACE_RECORDER")


    def test_clocked_native_current_ledger_keeps_distinct_provenance(self):
        frame=self.frame(1,250,4294967050)
        frame.qualifier="EXTERNAL_CLOCKED_CURRENT_CONTINUOUS_NO_AVERAGE"
        ledger={
            "scope":"HOST_ONLY_EXPLICIT_LEG_IDEAL_DIODE_CURRENT_CONTINUITY",
            "physical_motor_qualified":False,
            "real_native_guest_PWM_or_CAP1_qualified":False,
            "bus_input_energy_j":0.1,
        }
        source={
            "original_pwm_source":
              "EXECUTED_ORIGINAL_GUEST_QEMU_CLOCKED_PWM_HISTORY_NOT_DUTY_PLAN",
            "guest_sram_irq_pwm_register_writes":False,
            "calibrated_motor":False,
            "instantaneous_leg_model_only":True,
            "physical_model_integrated_ns":150,
            "actual_clocked_pwm_events":2,
        }
        self.observe(frame=frame,energy_balance=ledger,
                     clocked_source_evidence=source)
        recorded=self.rec.samples[0]
        self.assertEqual(recorded["integrated_ns"],150)
        self.assertEqual(recorded["actual_qemu_clocked_pwm_events"],2)
        self.assertEqual(recorded["legacy_sampled_hold_ns_not_motor_integrated"],250)
        self.assertEqual(recorded["sim_only_energy_balance"]["scope"],
                         ledger["scope"])

    def test_clocked_ledger_with_no_real_source_fails_closed(self):
        frame=self.frame(1,250,4294967050)
        frame.qualifier="EXTERNAL_CLOCKED_CURRENT_CONTINUOUS_NO_AVERAGE"
        ledger={
            "scope":"HOST_ONLY_EXPLICIT_LEG_IDEAL_DIODE_CURRENT_CONTINUITY",
            "physical_motor_qualified":False,
            "real_native_guest_PWM_or_CAP1_qualified":False,
        }
        with self.assertRaisesRegex(ValueError,"clocked Guest PWM provenance"):
            self.observe(frame=frame,energy_balance=ledger)
        self.assertEqual(self.rec.samples,[])

    def test_legacy_ledger_cannot_masquerade_as_clocked(self):
        with self.assertRaisesRegex(ValueError,"misclassified"):
            self.observe(energy_balance={
                "scope":"SIM_ONLY_SAMPLED_HOLD_NUMERICAL_ENERGY_DIAGNOSTIC",
                "numerical_energy_balance_qualified":False},
                clocked_source_evidence={"status":"fake"})
        self.assertEqual(self.rec.samples,[])


if __name__=="__main__":
    unittest.main(verbosity=2)
