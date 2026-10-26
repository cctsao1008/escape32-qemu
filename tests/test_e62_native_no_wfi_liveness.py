#!/usr/bin/env python3
"""Native E62 no-WFI host monitor should never tie FC traffic to guest."""
import inspect
import unittest
from e62_autonomous_native_motor_probe import (
    _autonomous_liveness, _wiring_failure_reasons, TimedAutonomousQTest, run)
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

    def test_final_coast_with_real_pwm_history_is_not_false_failure(self):
        autonomous={"pa26_capture":100,"pa26_dma":100}
        motor={
            "actual_pwm_event_notifications":500,
            "native_1us_physics_ticks":1000000,
            "analog_phase_code_updates":100,
            "model_fault":0,"status_flags":3
        }
        pwm={
            "running":False,"native_pwm_zero_callbacks":16000,
            "total_events":100000,"evaluator_valid":True,
            "native_pwm_invalid_level_events":0
        }
        self.assertEqual(_wiring_failure_reasons(autonomous,motor,pwm),[])
        pwm["native_pwm_zero_callbacks"]=0
        self.assertIn("NATIVE_MCPWM_CARRIER_NEVER_CLOCKED",
                      _wiring_failure_reasons(autonomous,motor,pwm))

    def test_command_deadline_is_limited_to_probe_adapter(self):
        self.assertIsNot(TimedAutonomousQTest.__init__,
                         __import__("g0_memory").QTest.__init__)


if __name__=="__main__":
    unittest.main(verbosity=2)
