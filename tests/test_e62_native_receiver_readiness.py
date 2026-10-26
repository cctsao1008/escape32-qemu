#!/usr/bin/env python3
"""No WFI/GDB/native stimulus until Guest DMA/ARM genuinely ready."""
import unittest
from e62_autonomous_native_motor_probe import _receiver_ready_reasons


class NativeReceiverReadinessTests(unittest.TestCase):
    def setUp(self):
        self.receiver={
            "cpu_primask":0,"cpu_exception_ipsr":0,
            "dma_ch2_trigger":34,"dma_ch2_control":0x2202,
            "dma_ch2_remaining":32,"dma_irq_raw":0,
            "native_oc_adc_codes":[0x103e8,0x103e8,0x103e8],
        }
        self.guest={"throt":1}

    def test_ready_only_after_all_original_conditions(self):
        self.assertEqual(_receiver_ready_reasons(self.receiver,self.guest),[])

    def test_original_startup_is_not_ready(self):
        self.receiver.update(cpu_primask=1,dma_ch2_control=0,
                             dma_ch2_trigger=0,dma_ch2_remaining=0)
        self.guest["throt"]=0
        reasons=_receiver_ready_reasons(self.receiver,self.guest)
        self.assertIn("ORIGINAL_CPU_INTERRUPT_MASKED",reasons)
        self.assertIn("ORIGINAL_DMA_CH2_DISABLED",reasons)
        self.assertIn("ORIGINAL_DMA_CH2_TRIGGER_NOT_TIMG4",reasons)
        self.assertIn("ORIGINAL_NEUTRAL_ARM_WINDOW_NOT_ENTERED",reasons)

    def test_fresh_32_beat_buffer_required(self):
        self.receiver["dma_ch2_remaining"]=0
        self.assertIn("ORIGINAL_DMA_CH2_NOT_FRESH_32_BEATS",
                      _receiver_ready_reasons(self.receiver,self.guest))

    def test_unsafe_oc_missing_not_overridden(self):
        self.receiver["native_oc_adc_codes"]=[0,0,0]
        self.assertIn("NATIVE_CURRENT_SENSE_NOT_VALID_AFTER_RESET",
                      _receiver_ready_reasons(self.receiver,self.guest))

    def test_dma_address_fault_must_fail_closed(self):
        self.receiver["dma_irq_raw"]=1<<24
        self.assertIn("ORIGINAL_DMA_ADDRESS_FAULT",
                      _receiver_ready_reasons(self.receiver,self.guest))

    def test_hardfault_cannot_be_called_ready(self):
        self.receiver["cpu_exception_ipsr"]=3
        self.assertIn("ORIGINAL_CPU_FAULT_EXCEPTION",
                      _receiver_ready_reasons(self.receiver,self.guest))


if __name__=="__main__":
    unittest.main(verbosity=2)
