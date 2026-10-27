#!/usr/bin/env python3
"""E62 ESC-SIM interactive Python CLI offline contract tests; no QEMU needed."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.e62_sim_cli import E62SimConsole,percent_to_permille
from tools.sitl_autonomous_transport import AUTO_BASE,REG


class FakeProc:
    def poll(self):return None


class FakeQTest:
    def __init__(self):
        self.regs={
            AUTO_BASE+REG["status"]:1,
            AUTO_BASE+REG["sent"]:20,
            AUTO_BASE+REG["live_override"]:0,
            AUTO_BASE+REG["live_permille"]:0,
            AUTO_BASE+REG["live_changes"]:0,
        }
        self.writes=[]
    def read(self,addr):
        return self.regs.get(addr,0)
    def write(self,addr,value):
        assert addr in (AUTO_BASE+REG["live_override"],
                        AUTO_BASE+REG["live_permille"]), hex(addr)
        self.writes.append((addr,value))
        self.regs[addr]=value


def console():
    return E62SimConsole(
        qemu=Path("/nonexistent/qemu"),elf=Path("/nonexistent/original.elf"),
        cfg_flash=Path("/nonexistent/native-cfg.bin"),
        scenario=ROOT/"scenarios/e62-native-console-10s.json",
        artifacts=ROOT/"artifacts"
    )


class E62PythonConsoleContracts(unittest.TestCase):
    def test_scenario_is_exactly_continuous_zero_fc_before_live_commands(self):
        c=console()
        self.assertEqual(c.meta["dshot_frames"],10000)
        self.assertEqual(c.stages,[(1500,0,0,1),(8500,0,0,1)])
        self.assertFalse(c.active)

    def test_percent_scaling_boundaries_and_bad_guest_value(self):
        self.assertEqual(percent_to_permille("0"),0)
        self.assertEqual(percent_to_permille("15.5"),155)
        self.assertEqual(percent_to_permille("100"),1000)
        for value in ("-1","100.1","9.55","1e3","nan","blah"):
            with self.subTest(value=value),self.assertRaises(ValueError):
                percent_to_permille(value)

    def test_esc_style_live_throt_touches_fc_input_only(self):
        c=console();q=FakeQTest();c.qtest=q;c.proc=FakeProc()
        with redirect_stdout(io.StringIO()) as out:
            c.do_throt("15.5")
            c.do_throt("auto")
        self.assertEqual(q.writes,[
            (AUTO_BASE+REG["live_permille"],155),
            (AUTO_BASE+REG["live_override"],1),
            (AUTO_BASE+REG["live_override"],0),
        ])
        self.assertTrue(c.live_changed)
        self.assertIn("OK FC command",out.getvalue())

    def test_running_scenario_cannot_be_replaced(self):
        c=console();c.qtest=FakeQTest();c.proc=FakeProc()
        oldsha=c.meta["sha256"]
        with redirect_stdout(io.StringIO()) as out:
            c.do_load(str(ROOT/"scenarios/e62-native-p0-smoke.json"))
        self.assertIn("ERROR load:",out.getvalue())
        self.assertEqual(c.meta["sha256"],oldsha)

    def test_get_and_show_no_arbitrary_guest_rw(self):
        c=console()
        with redirect_stdout(io.StringIO()) as out:
            c.do_show("scenario")
            c.do_get("guest.throt")
            c.do_set("motor.rpm 100")
        self.assertIn("SCENARIO",out.getvalue())
        self.assertIn("ERROR get:",out.getvalue())
        self.assertIn("only 'set monitor_interval",out.getvalue())

    def test_fault_scenario_staged_only_when_not_running(self):
        c=console()
        c.load_scenario(ROOT/"scenarios/e62-native-p0-smoke.json")
        with redirect_stdout(io.StringIO()) as out:
            c.do_fault("load scenarios/e62-native-p1-nfault.json")
        # relative paths below work from repo root in CI, as for console docs
        self.assertEqual(c.fault_plan["assert_frame"],2100)
        self.assertIn("OK fault fixture loaded",out.getvalue())


if __name__=="__main__":
    unittest.main(verbosity=2)
