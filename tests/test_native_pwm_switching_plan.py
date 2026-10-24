#!/usr/bin/env python3
"""G13B3 read-only QEMU AQ/DB carrier-plan provenance and fail-closed decoder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_pwm_switching_plan import (
    SWITCH_BASE, CarrierModelEdge, capture_qemu_carrier_plan,
    reconstruct_high_ticks)
from tools.native_pwm_qualification import (
    MCPWM4,SYSCTL_PERCLKCR,SYSCTL_PWREN)
from tools.virtual_bldc import (
    OBS_BASE, GPIO1_BASE, PINCM_BASE, MCPWM4_ROUTES, GATE_EN)


def fixture():
    regs = {
        SWITCH_BASE: 0x50323645, SWITCH_BASE+4: 0x0b,
        SWITCH_BASE+8: 100, SWITCH_BASE+12: 4,
        SWITCH_BASE+16: 0x15, SWITCH_BASE+20: 0,
        SWITCH_BASE+24: 100_000_000, SWITCH_BASE+28: 0,
        SWITCH_BASE+32: 42, SWITCH_BASE+36: 123,
        SWITCH_BASE+40: 1, SWITCH_BASE+44: 1,
        OBS_BASE: 9, OBS_BASE+8: 100, OBS_BASE+0x14: 0x3f,
        MCPWM4+0xb0: 0,
        GPIO1_BASE+0x800:1,
        GPIO1_BASE+0x12c0:GATE_EN,
        GPIO1_BASE+0x1280:GATE_EN,
        PINCM_BASE+4*45:0x81,
        SYSCTL_PWREN:0x200, SYSCTL_PERCLKCR:1,
    }
    for i,(tick,mask) in enumerate(((25,20),(40,16),(60,0),(100,21))):
        regs[SWITCH_BASE+0x40+8*i]=tick
        regs[SWITCH_BASE+0x44+8*i]=mask
    for idx,count in enumerate((25,0,40,0,60,0)):
        regs[OBS_BASE+0x18+4*idx]=count
    for pin,mux in MCPWM4_ROUTES:
        regs[PINCM_BASE+4*pin]=0x80|mux
    return regs


class ReadOnlyCarrierPlan(unittest.TestCase):
    def test_switching_plan_mmio_address_is_unique(self):
        from tools.native_pwm_switching_plan import SWITCH_BASE
        from pathlib import Path
        import re
        root=Path(__file__).resolve().parents[1]
        macro_sources={
            "C PWM": root/"machine/am13e23019.c",
            "PA26":root/"machine/am13e_pa26_waveform.inc",
            "Fault":root/"machine/am13e_trip_safety.inc",
            "BEMF":root/"machine/am13e_motor_feedback.inc",
        }
        all_source="\n".join(f.read_text() for f in macro_sources.values())
        def macro(k):
            values=re.findall(r"^#define\s+"+re.escape(k)+r"\s+(0x[0-9a-fA-F]+)U",all_source,re.M)
            self.assertEqual(len(values),1,k)
            return int(values[0],16)
        # Do not repeat the 0x5ffe4000 collision: already PA26 waveform.
        self.assertEqual(SWITCH_BASE,0x5ffe6000)
        self.assertEqual(SWITCH_BASE,macro("AM13E_SIM_PWM_SWITCH_OBSERVER"))
        own_size=macro("AM13E_SIM_PWM_SWITCH_OBS_SIZE")
        windows=(
            ("AM13E_PA26_WAVE_BASE","AM13E_PA26_WAVE_SIZE"),
            ("AM13E_G13B2_SOURCE_BASE",None),
            ("AM13E_G10_STIM_BASE",None),
            ("AM13E_SIM_PWM_OBSERVER","AM13E_SIM_PWM_OBS_SIZE"),
            ("AM13E_G11_ARCH_OBS_BASE","AM13E_G11_ARCH_OBS_SIZE"),
            ("AM13E_SIM_PA26_INJECT_BASE","AM13E_SIM_PA26_INJECT_SIZE"),
        )
        for start_key,size_key in windows:
            start=macro(start_key)
            size=macro(size_key) if size_key else 0x100
            self.assertTrue(
                SWITCH_BASE+own_size<=start or
                start+size<=SWITCH_BASE, start_key)

    def test_source_evaluated_edges_match_all_six_high_counts(self):
        regs=fixture()
        x=capture_qemu_carrier_plan(lambda address:regs[address])
        self.assertEqual(x.period_ticks,100)
        self.assertEqual(x.six_high_ticks,(25,0,40,0,60,0))
        self.assertEqual(x.initial_mask,21)
        self.assertEqual(x.last_mask,0)
        self.assertTrue(x.original_gate_and_trip_qualified)
        self.assertEqual(x.sampled_native_zero_count,42)
        self.assertEqual(x.snapshot_virtual_ns,1<<32|123)
        self.assertEqual(x.edges[-1],CarrierModelEdge(100,21))
        d=x.to_dict()
        for key in (
            "historical_chronological_edge_callbacks_observed",
            "midcarrier_register_changes_observed",
            "physical_gate_driver_deadtime_qualified",
            "external_mosfet_output_edges_measured",
            "physical_freewheel_topology_qualified",
            "current_continuous_plant_input_qualified",
            "native_closed_loop_motor_qualified",
        ):
            self.assertFalse(d[key])

    def test_not_a_physical_output_without_external_gate(self):
        regs=fixture()
        regs[GPIO1_BASE+0x1280]=0
        x=capture_qemu_carrier_plan(lambda address:regs[address])
        self.assertFalse(x.original_gate_and_trip_qualified)
        self.assertFalse(x.to_dict()["current_continuous_plant_input_qualified"])

    def test_reject_overflow_or_invalid_active_aq_db(self):
        for value in (0x09,0x0f,0x00,0x17):
            regs=fixture(); regs[SWITCH_BASE+4]=value
            with self.assertRaisesRegex(ValueError,"not running/valid"):
                capture_qemu_carrier_plan(lambda address:regs[address])

    def test_reject_unqualified_edge_count_or_period(self):
        for address,value in (
            (SWITCH_BASE+12,65),(SWITCH_BASE+8,0),
            (SWITCH_BASE+8,65537),(SWITCH_BASE+24,0),
            (SWITCH_BASE+28,100)):
            regs=fixture();regs[address]=value
            with self.assertRaises(ValueError):
                capture_qemu_carrier_plan(lambda address:regs.get(address,0))

    def test_reject_changed_source_state_during_read(self):
        regs=fixture(); reads=0
        def changing(address):
            nonlocal reads
            reads+=1
            # Second header begins after 12+8+the existing physical outputs.
            if address==SWITCH_BASE+32 and reads>25:
                return 43
            return regs[address]
        with self.assertRaisesRegex(ValueError,"source changed"):
            capture_qemu_carrier_plan(changing)

    def test_reject_duty_mismatch_even_if_edge_plan_internally_valid(self):
        regs=fixture()
        regs[OBS_BASE+0x18]=26
        with self.assertRaisesRegex(ValueError,"disagree"):
            capture_qemu_carrier_plan(lambda address:regs[address])

    def test_reject_nonphysical_same_leg_overlap(self):
        regs=fixture()
        regs[SWITCH_BASE+16]=0x03
        regs[SWITCH_BASE+20]=0x03
        regs[SWITCH_BASE+12]=0
        with self.assertRaisesRegex(ValueError,"simultaneous H/L"):
            capture_qemu_carrier_plan(lambda address:regs.get(address,0))

    def test_reject_missing_wrap_transition(self):
        with self.assertRaisesRegex(ValueError,"Missing period-wrap"):
            reconstruct_high_ticks(
                period_ticks=100,initial_mask=1,
                edges=(CarrierModelEdge(25,0),))

    def test_reject_redundant_or_out_of_order_edges(self):
        for edges in (
            (CarrierModelEdge(10,1),),
            (CarrierModelEdge(50,0),CarrierModelEdge(49,1)),
            (CarrierModelEdge(101,0),),
            (CarrierModelEdge(2,65),),
        ):
            with self.assertRaises(ValueError):
                reconstruct_high_ticks(
                    period_ticks=100,initial_mask=1,edges=edges)

    def test_reject_bad_abi_or_magic(self):
        for address,value in (
            (SWITCH_BASE,0),(SWITCH_BASE+44,2)):
            regs=fixture(); regs[address]=value
            with self.assertRaises(ValueError):
                capture_qemu_carrier_plan(lambda address:regs[address])


if __name__=="__main__":
    unittest.main(verbosity=2)
