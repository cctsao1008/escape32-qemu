#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.functional_dshot_scenario import load_scenario
from tools.autonomous_sitl_host import (
    compile_autonomous_stages, configure_auto, read_auto,
    read_stage_checkpoints, summarize_stage_samples, native_end_oracle,
    AUTO_BASE, AUTO_MAGIC, AUTO_ABI, AUTO_RUNNING, AUTO_DONE, REG)


class MockQTest:
    def __init__(self):
        self.mem = {AUTO_BASE+REG['magic']: AUTO_MAGIC,
                    AUTO_BASE+REG['status']: AUTO_RUNNING,
                    AUTO_BASE+REG['abi_version']: AUTO_ABI,
                    AUTO_BASE+REG['schema_magic']:0x53363134}
        self.evidence_by_stage = {}
    def write(self, addr, val):
        self.mem[addr] = val
        if addr == AUTO_BASE+REG['command'] and val == 1:
            self.mem[AUTO_BASE+REG['status']] = AUTO_RUNNING
            self.mem[AUTO_BASE+REG['target_frames']] = (
                self.mem.get(AUTO_BASE+REG['max_frames']) or 50)
    def read(self,addr):
        which = self.mem.get(AUTO_BASE+REG['stage_query'],0)
        if addr in [AUTO_BASE+REG[k] for k in
                     ('stage_end_sent','stage_end_capture','stage_end_dma',
                      'stage_end_crossings','stage_status','stage_end_ms',
                      'stage_end_bemf_callbacks','stage_end_analog_updates')]:
            return self.evidence_by_stage.get(which,{}).get(addr,0)
        return self.mem.get(addr,0)


class AutonomousTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p=Path(__file__).resolve().parents[1]/'scenarios/e62-dshot-v1.json'
        cls.t01=load_scenario(p,'T01')
        cls.t02=load_scenario(p,'T02')

    def test_exact_t01_and_t02_stages(self):
        a=compile_autonomous_stages(self.t01)
        b=compile_autonomous_stages(self.t02)
        self.assertEqual(a,[dict(duration_ms=1000,start_permille=0,
                  end_permille=900,update_ms=10),
                  dict(duration_ms=10000,start_permille=900,
                  end_permille=900,update_ms=1)])
        self.assertEqual(len(b),11)
        self.assertEqual(sum(i['duration_ms'] for i in b),110000)
        self.assertEqual([i['start_permille'] for i in b],
                         list(range(0,1001,100)))

    def test_mock_port_write_readback_and_bound(self):
        q=MockQTest()
        result=configure_auto(q,self.t01,max_frames=50)
        self.assertEqual(result['target_frames'],50)
        self.assertEqual(q.mem[AUTO_BASE+REG['stage_count']],2)

    def test_absent_port_fails(self):
        q=MockQTest()
        q.mem[AUTO_BASE+REG['magic']]=0
        with self.assertRaises(RuntimeError):
            configure_auto(q,self.t01,max_frames=50)

    def test_aggregate_not_falsely_stage_qualified(self):
        base={'pa26_capture':0,'pa26_dma':0,'valid_frame_feeds':0,
              'captured_events':0,'serviced':0}
        end={'valid_frame_feeds':42,'captured_events':10,'serviced':9,'throt':1847}
        snapshot={'status':AUTO_DONE,'error':0,'sent':11000,
                  'target_frames':11000,'elapsed_ns':11_000_000_000,
                  'pa26_capture':22000,'pa26_dma':22000,
                  'pwm_samples':9,'bemf_crossings':5}
        status,issues=native_end_oracle(snapshot,base,end,self.t01)
        self.assertEqual((status,issues),
                         ('PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL',[]))
        snapshot['bemf_crossings']=0
        status,issues=native_end_oracle(snapshot,base,end,self.t01)
        self.assertEqual(status,'FAIL_AUTONOMOUS_ORACLE')

    def test_old_autonomous_abi_is_rejected(self):
        q = MockQTest()
        q.mem[AUTO_BASE+REG['abi_version']] = 1
        with self.assertRaisesRegex(RuntimeError,'ABI'):
            configure_auto(q,self.t01,max_frames=50)
        with self.assertRaisesRegex(RuntimeError,'ABI'):
            read_auto(q.read)

    def test_stage_checkpoint_readback_is_not_crc_proof(self):
        q = MockQTest()
        q.evidence_by_stage = {
            0:{AUTO_BASE+REG['stage_status']:3,
               AUTO_BASE+REG['stage_end_sent']:1000,
               AUTO_BASE+REG['stage_end_capture']:32064,
               AUTO_BASE+REG['stage_end_dma']:30700,
               AUTO_BASE+REG['stage_end_crossings']:600,
               AUTO_BASE+REG['stage_end_ms']:1000,
               AUTO_BASE+REG['stage_end_bemf_callbacks']:1200,
               AUTO_BASE+REG['stage_end_analog_updates']:800},
            1:{AUTO_BASE+REG['stage_status']:3,
               AUTO_BASE+REG['stage_end_sent']:11000,
               AUTO_BASE+REG['stage_end_capture']:352064,
               AUTO_BASE+REG['stage_end_dma']:338000,
               AUTO_BASE+REG['stage_end_crossings']:9000,
               AUTO_BASE+REG['stage_end_ms']:11000,
               AUTO_BASE+REG['stage_end_bemf_callbacks']:18000,
               AUTO_BASE+REG['stage_end_analog_updates']:17000}}
        cp=read_stage_checkpoints(q,self.t01)
        self.assertEqual([x['end_sent_cumulative'] for x in cp],[1000,11000])
        self.assertTrue(all(x['valid'] and x['complete'] for x in cp))
        self.assertEqual(cp[0]['end_elapsed_ms'],1000)
        self.assertNotIn('guest_crc',cp[0])
        self.assertEqual(q.mem[AUTO_BASE+REG['stage_query']],1)

    def test_async_stage_samples_are_not_stage_pass(self):
        samples=[
            dict(sim_elapsed_ms=100,sim_dshot_value=228,
                 guest_throt_sample=180,guest_valid_crc_feed_total=80,
                 pwm_high_tick_ratios_sample=None),
            dict(sim_elapsed_ms=900,sim_dshot_value=1667,
                 guest_throt_sample=1600,guest_valid_crc_feed_total=770,
                 pwm_high_tick_ratios_sample=[.5]*6),
            dict(sim_elapsed_ms=1100,sim_dshot_value=1847,
                 guest_throt_sample=1847,guest_valid_crc_feed_total=920,
                 pwm_high_tick_ratios_sample=[.7]*6)]
        rows=summarize_stage_samples(self.t01,samples)
        self.assertEqual([r['sample_count'] for r in rows],[2,1])
        self.assertEqual(rows[0]['guest_throttle_last'],1600)
        self.assertEqual(rows[1]['last_sample_command_dshot'],1847)
        self.assertIn('NOT_STAGE_ORACLE',rows[1]['provenance'])

    def test_incomplete_stage_checkpoint_is_explicit(self):
        q=MockQTest()
        q.evidence_by_stage={
            0:{AUTO_BASE+REG['stage_status']:1,
               AUTO_BASE+REG['stage_end_sent']:50,
               AUTO_BASE+REG['stage_end_capture']:1664,
               AUTO_BASE+REG['stage_end_dma']:1592,
               AUTO_BASE+REG['stage_end_ms']:50}}
        rows=read_stage_checkpoints(q,self.t01,max_frames=50)
        self.assertTrue(rows[0]['valid'])
        self.assertFalse(rows[0]['complete'])
        self.assertFalse(rows[1]['valid'])


if __name__=='__main__':
    unittest.main(verbosity=2)
