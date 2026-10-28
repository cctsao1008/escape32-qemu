#!/usr/bin/env python3
"""Native E62 no-WFI host monitor should never tie FC traffic to guest."""
import ast
import inspect
import textwrap
import unittest
from e62_autonomous_native_motor_probe import (
    _autonomous_liveness, _wiring_failure_reasons, TimedAutonomousQTest, run)
from tools.sitl_autonomous_transport import AUTO_BASE, REG


def _forbidden_guest_execution_controls(function_source):
    """Check executable syntax, not harmless log keys or comments.

    Reject real GDB launch flags and QTest clock/CPU stepping. Diagnostic
    initial -S + QMP configuration remains separate from the default
    autonomous no-WFI monitor; this check cannot qualify P0/P1 physics.
    """
    syntax = ast.parse(textwrap.dedent(function_source))
    forbidden_flags = {"-gdb", "-s", "-singlestep"}
    forbidden_qtest = {"clock_step", "clock_set", "clock_step_next",
                       "irq_intercept_in", "irq_intercept_out"}
    findings = []
    for node in ast.walk(syntax):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in forbidden_flags:
                findings.append("QEMU GDB/singlestep flag: " + node.value)
        if (isinstance(node, ast.Call) and
            isinstance(node.func, ast.Attribute) and
            node.func.attr == "cmd" and node.args and
            isinstance(node.args[0], ast.Constant) and
            isinstance(node.args[0].value, str)):
            command = node.args[0].value.split(maxsplit=1)
            if command and command[0] in forbidden_qtest:
                findings.append("host QTest clock/IRQ control: " + command[0])
    return findings


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
        self.assertEqual(_forbidden_guest_execution_controls(body), [])
        self.assertIn("_autonomous_liveness(qtest.read)",body)
        self.assertNotIn("_wait_for_original_receiver_ready(",body)
        self.assertNotIn("NativeClockedCurrentCoupler",body)

    def test_comments_and_diagnostic_metadata_are_not_execution_controls(self):
        source = '''
def run():
    # Default run uses no -gdb.
    evidence = {"used_guest_wfi_or_gdb": False}
    command = ["qemu", "-S", "-qmp", "unix:/tmp/qmp.sock"]
'''
        self.assertEqual(_forbidden_guest_execution_controls(source), [])

    def test_real_gdb_or_qtest_clock_injection_is_rejected(self):
        for source in (
            'def run():\n    cmd = ["qemu", "-gdb", "tcp::1234"]\n',
            'def run():\n    cmd = ["qemu", "-s"]\n',
            'def run():\n    qtest.cmd("clock_step 1000")\n',
            'def run():\n    qtest.cmd("clock_step_next")\n',
        ):
            with self.subTest(source=source):
                self.assertTrue(_forbidden_guest_execution_controls(source))

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
