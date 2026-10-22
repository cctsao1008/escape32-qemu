#!/usr/bin/env python3
"""Only external PA26 waveform sequencing; never Guest register edits."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tests"))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from g13b_native_dshot import WAVE,queue_dshot600_wire
from g13b2_native_drive_probe import native_pa26_receiver_rearm_snapshot
from g13b_native_dshot import DMA


class ExternalPA26Fixture:
    def __init__(self):
        self.queued=0
        self.delivered=0
        self.running=0
        self.delay=None
        self.level=None
        self.staged=[]
        self.arm_calls=0
        self.reset_calls=0
    def read(self,addr):
        offset=addr-WAVE
        return {8:self.queued,12:self.delivered,16:self.running,
                20:(self.staged[-1][1] if self.staged else 0)}[offset]
    def write(self,addr,value):
        offset=addr-WAVE
        if offset==0:
            self.delay=value
        elif offset==4:
            self.level=value
        elif offset==0x18:
            if value!=1 or self.running or self.delay is None or self.level is None:
                raise AssertionError("Invalid physical edge staging")
            self.queued+=1
            self.staged.append((self.delay,self.level))
            self.delay=self.level=None
        elif offset==0x1c:
            if value!=1 or self.queued!=32 or self.delivered or self.running:
                raise AssertionError("Illegal PA26 waveform start")
            self.running=1
            self.arm_calls+=1
        elif offset==0x20:
            if value!=1 or self.running:
                raise AssertionError("Cannot clear active PA26 wire")
            self.queued=self.delivered=0
            self.delay=self.level=None
            self.staged=[]
            self.reset_calls+=1
        else:
            raise AssertionError("Not external PA26 WAVE port")
    def finish(self):
        self.running=0
        self.delivered=self.queued


class OriginalArmZeroWireTests(unittest.TestCase):
    def test_genuine_zero_then_genuine_throttle_are_two_physical_frames(self):
        q=ExternalPA26Fixture()
        self.assertEqual(queue_dshot600_wire(q,0,allow_zero=True),0)
        self.assertEqual(q.queued,32)
        self.assertEqual(q.arm_calls,1)
        self.assertEqual(q.staged[-1][1],0)
        q.finish()
        frame=queue_dshot600_wire(q,1500,reset_completed_wave=True)
        self.assertNotEqual(frame,0)
        self.assertEqual(q.reset_calls,1)
        self.assertEqual(q.queued,32)
        self.assertEqual(q.arm_calls,2)
    def test_repeated_actual_positive_packets_keep_wire_history(self):
        # This only checks the simulator's external physical input
        # queue. A native ARM/CRC PASS still requires original ELF CI.
        q = ExternalPA26Fixture()
        queue_dshot600_wire(q, 0, allow_zero=True)
        q.finish()
        queue_dshot600_wire(q, 1500, reset_completed_wave=True)
        q.finish()
        queue_dshot600_wire(q, 1500, reset_completed_wave=True)
        self.assertEqual(q.reset_calls, 2)
        self.assertEqual(q.arm_calls, 3)
        self.assertEqual(q.queued, 32)
        self.assertEqual(q.staged[-1][1], 0)
    def test_original_dma_rearm_requires_full_32_word_buffer(self):
        class ReadOnlyDma:
            def __init__(self, size, ctrl, trig, raw=0):
                self.values={
                    DMA+0x1000+0x220: ctrl,
                    DMA+0x1000+0x22c: size,
                    DMA+0x1000+0x118: trig,
                    DMA+0x1000+0x030: raw,
                }
                self.reads=[]
            def read(self, address):
                self.reads.append(address)
                return self.values[address]
        for size, ctrl, trig, raw, expected in (
                (32, 2, 34, 0, True),
                (7, 2, 34, 0, False),
                (32, 0, 34, 0, False),
                (32, 2, 35, 0, False),
                (32, 2, 34, 1<<24, False)):
            q=ReadOnlyDma(size,ctrl,trig,raw)
            snap=native_pa26_receiver_rearm_snapshot(q)
            self.assertEqual(snap["source_owned_fresh_rx_buffer"],expected)
            self.assertFalse(snap["guest_register_writes"])
            self.assertEqual(len(q.reads),4)

    def test_neutral_requires_explicit_arm_permission(self):
        q=ExternalPA26Fixture()
        with self.assertRaisesRegex(ValueError,"opt-in zero"):
            queue_dshot600_wire(q,0)
        self.assertEqual(q.queued,0)
    def test_inflight_wave_must_never_be_reset(self):
        q=ExternalPA26Fixture()
        queue_dshot600_wire(q,0,allow_zero=True)
        with self.assertRaisesRegex(AssertionError,"active/undelivered"):
            queue_dshot600_wire(q,1500,reset_completed_wave=True)
        self.assertEqual(q.reset_calls,0)
    def test_only_simulator_external_io_is_ever_written(self):
        q=ExternalPA26Fixture()
        queue_dshot600_wire(q,0,allow_zero=True)
        self.assertEqual(q.queued,32)
        self.assertTrue(all(level in (0,1) and delay>=10 for delay,level in q.staged))


if __name__=="__main__":
    unittest.main(verbosity=2)
