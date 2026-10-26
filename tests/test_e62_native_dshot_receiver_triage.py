#!/usr/bin/env python3
"""Exact negative controls for offline original Guest CPU/DMA triage."""
import unittest
from tools.ci.e62_native_dshot_receiver_triage import diagnose


def sample(*,ipsr=0,primask=0,raw=0x40004,mask=0x1040004,trip=0x40000):
    return {
      "autonomous_dshot":{"sent":3000,"status":2},
      "receiver_after":{
        "cpu_pc":0x679a,"cpu_lr":0x1234,
        "cpu_exception_ipsr":ipsr,"cpu_primask":primask,
        "dma_irq_raw":raw,"dma_irq_mask":mask,
        "dma_irq_masked":raw & mask,
        "dma_ch2_remaining":0,"dma_ch2_control":0,
        "dma_ch2_trigger":34,
        "native_ost_latched":trip,
        "native_oc_adc_codes":[0x103e8]*3,
      },
      "original_guest_after":{"valid_frame_feeds":0}
    }


class OfflineTriageTests(unittest.TestCase):
    def test_pending_is_not_falsely_claimed_to_prove_nvic_failure(self):
        got=diagnose(sample())
        self.assertEqual(got["classification"],"DMA_PENDING_DELIVERY_UNRESOLVED")
        self.assertIn("PENDING_DMA_IRQ_DOES_NOT_PROVE_MISSING_NVIC_DELIVERY",
                      got["warnings"])
        self.assertIn("MOTOR_POWER_TRIP_LATCHED_INDEPENDENT_OF_DMA",
                      got["observations"])

    def test_dma_handler_currently_active(self):
        got=diagnose(sample(ipsr=56))
        self.assertEqual(got["classification"],"DMA0_ISR_ACTIVE")
        self.assertEqual(got["nvic_active_external_irq"],40)

    def test_masked_interrupts_more_direct_than_pending(self):
        got=diagnose(sample(primask=1))
        self.assertEqual(got["classification"],"CPU_INTERRUPTS_MASKED")

    def test_cpu_fault_is_not_mistaken_for_dma_mapping_defect(self):
        got=diagnose(sample(ipsr=3,primask=1))
        self.assertEqual(got["classification"],"CPU_FAULT_OBSERVED")

    def test_absent_terminal_snapshot_fails_closed(self):
        got=diagnose({"last_successful_dshot_poll":{"sent":3000}})
        self.assertEqual(got["classification"],"NO_TERMINAL_CPU_IRQ_SNAPSHOT")
        self.assertEqual(got["dshot_sent"],3000)

    def test_stage_fallback_is_explicitly_labeled(self):
        got=diagnose({"runtime_diagnostics_by_stage":[
            {"receiver_and_cpu":sample()["receiver_after"],
             "original_guest":{"valid_frame_feeds":0}}]})
        self.assertEqual(got["source_snapshot"],"last_stage")


if __name__=="__main__":
    unittest.main(verbosity=2)
