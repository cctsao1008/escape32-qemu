#!/usr/bin/env python3
"""Native E62 no-WFI host monitor should never tie FC traffic to guest."""
import inspect
import unittest
from e62_autonomous_native_motor_probe import (
    _autonomous_liveness, TimedAutonomousQTest, run)
from tools.sitl_autonomous_transport import AUTO_BASE, REG


class NoWfiLightweightMonitorTests(unittest.TestCase):
    def test_poll_uses_only_three_readonly_simulator_status_registers(self):
        calls=[]
        readings={
            AUTO_BASE+REG["status"]:1,
            AUTO_BASE+REG["sent"]:250,
            AUTO_BASE+REG["stage"]:1,
        }
        def read(addr):
            calls.append(addr)
            return readings[addr]
        self.assertEqual(_autonomous_liveness(read),
                         dict(status=1,sent=250,stage=1))
        self.assertEqual(calls,[
            AUTO_BASE+REG["status"], AUTO_BASE+REG["sent"],
            AUTO_BASE+REG["stage"]
        ])

    def test_host_monitor_does_not_step_cpu_or_submit_bemf(self):
        body=inspect.getsource(run)
        self.assertNotIn('gdb',body.lower().split("# deliberately")[0])
        self.assertIn("_autonomous_liveness(qtest.read)",body)
        self.assertNotIn("_wait_for_original_receiver_ready(",body)
        self.assertNotIn("NativeClockedCurrentCoupler",body)

    def test_command_deadline_is_limited_to_probe_adapter(self):
        self.assertIsNot(TimedAutonomousQTest.__init__,
                         __import__("g0_memory").QTest.__init__)


if __name__=="__main__":
    unittest.main(verbosity=2)
