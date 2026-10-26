#!/usr/bin/env python3
"""Fail-closed, read-only E62 no-WFI first-DShot-frame classifier."""
import unittest
from e62_autonomous_native_motor_probe import _classify_receive_path


def fixture():
    auto={"sent":750,"pa26_capture":23616,"pa26_dma":32}
    guest={"valid_frame_feeds":0}
    receiver={"dma_ch2_remaining":0,
              "dma_irq_masked":0,"cpu_exception_ipsr":0,
              "native_ost_latched":0}
    return auto,guest,receiver


class ReceiverDiagnosticsTest(unittest.TestCase):
    def test_first_dma_buffer_not_rearmed_is_not_motor_fault(self):
        auto,guest,receiver=fixture()
        reasons=_classify_receive_path(auto,guest,receiver)
        self.assertIn("DMA_CH2_ONLY_ONE_FRAME_OR_LESS_DESPITE_PA26_EDGES",reasons)
        self.assertIn("ORIGINAL_GUEST_NO_VALID_DSHOT_FRAME",reasons)
        self.assertIn("DMA_CH2_FIRST_BUFFER_EXHAUSTED_NOT_REARMED_AT_SAMPLE",reasons)
        self.assertNotIn("GUEST_CPU_IN_FAULT_EXCEPTION_AT_SAMPLE",reasons)
        self.assertNotIn("DMA0_IRQ_PENDING_MASKED_STATUS_NONZERO_AT_SAMPLE",reasons)

    def test_pending_dma_irq_and_hard_fault_are_distinct(self):
        auto,guest,receiver=fixture()
        receiver["dma_irq_masked"]=1<<2
        receiver["cpu_exception_ipsr"]=3
        reasons=_classify_receive_path(auto,guest,receiver)
        self.assertIn("DMA0_IRQ_PENDING_MASKED_STATUS_NONZERO_AT_SAMPLE",reasons)
        self.assertIn("GUEST_CPU_IN_FAULT_EXCEPTION_AT_SAMPLE",reasons)

    def test_receiving_guest_does_not_emit_false_stall(self):
        auto,guest,receiver=fixture()
        auto["pa26_dma"]=23616
        guest["valid_frame_feeds"]=720
        receiver["dma_ch2_remaining"]=32
        self.assertEqual(_classify_receive_path(auto,guest,receiver),[])

    def test_no_statement_before_enough_physical_frames(self):
        auto,guest,receiver=fixture()
        auto["sent"]=1
        auto["pa26_capture"]=32
        auto["pa26_dma"]=32
        receiver["dma_ch2_remaining"]=0
        reasons=_classify_receive_path(auto,guest,receiver)
        self.assertNotIn("ORIGINAL_GUEST_NO_VALID_DSHOT_FRAME",reasons)
        self.assertNotIn("DMA_CH2_ONLY_ONE_FRAME_OR_LESS_DESPITE_PA26_EDGES",reasons)


if __name__=="__main__":
    unittest.main(verbosity=2)
