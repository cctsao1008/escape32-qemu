#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.functional_dshot_scenario import load_scenario
from tools.autonomous_sitl_host import (
    compile_autonomous_stages, configure_auto, read_auto, native_end_oracle,
    AUTO_BASE, AUTO_MAGIC, AUTO_RUNNING, AUTO_DONE, REG)


class MockQTest:
    def __init__(self):
        self.mem = {AUTO_BASE+REG['magic']: AUTO_MAGIC,
                    AUTO_BASE+REG['status']: AUTO_RUNNING}
    def write(self, addr, val):
        self.mem[addr] = val
        if addr == AUTO_BASE+REG['command'] and val == 1:
            self.mem[AUTO_BASE+REG['status']] = AUTO_RUNNING
            self.mem[AUTO_BASE+REG['target_frames']] = (
                self.mem.get(AUTO_BASE+REG['max_frames']) or 50)
    def read(self,addr):
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


if __name__=='__main__':
    unittest.main(verbosity=2)
