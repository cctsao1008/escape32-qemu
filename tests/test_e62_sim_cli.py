#!/usr/bin/env python3
"""E62 ESC-SIM interactive Python CLI offline contract tests; no QEMU needed."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.e62_sim_cli import E62SimConsole,percent_to_permille,_six_pad_levels
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

    def test_raw_six_pad_mask_is_not_misreported_as_motor_drive(self):
        self.assertEqual(_six_pad_levels(0x0a),"U_L,V_L")
        self.assertEqual(_six_pad_levels(0),"none")
        self.assertEqual(_six_pad_levels(0x21),"U_H,W_L")

    def test_scenario_shows_named_percent_fields(self):
        c=console()
        with redirect_stdout(io.StringIO()) as out:
            c.do_show("scenario")
        data=out.getvalue()
        self.assertIn('"from_percent": 0.0',data)
        self.assertIn('"duration_ms": 1500',data)
        self.assertIn('"total_virtual_ms": 10000',data)
        self.assertNotIn('"stage_rows"',data)

    def test_manual_stop_preserves_explicit_unqualified_json_and_trace(self):
        import json
        import tempfile
        c=console()
        with tempfile.TemporaryDirectory() as tmp:
            c.run_artifact=Path(tmp)/"console.json"
            c.log_path=Path(tmp)/"console.qemu.log"
            c.log_path.write_text(
                "E62_P0_EVENT seq=1 vns=0 kind=DSHOT a=0 b=0 c=0 d=0 e=0 f=0\n"
                "E62_P0_EVENT seq=2 vns=1 kind=THROT_SET a=1 b=1 c=0 d=2 e=0 f=0\n")
            result=c._write_interrupted_evidence({"sent":90},10,None)
            record=json.loads(result.read_text())
            self.assertEqual(record["status"],"STOPPED_BY_OPERATOR_NOT_A_TEST_PASS")
            self.assertFalse(record["qualified"])
            self.assertFalse(record["motor_safe_stop_proven"])
            self.assertEqual(record["source_dshot_before_stop"]["sent"],90)
            self.assertTrue(record["neutral_source_frames_confirmed"])
            self.assertEqual(record["p0_source_event_count"],2)
            self.assertEqual(
                Path(record["p0_event_trace_path"]).read_text().count("E62_P0_EVENT"),2)

    def test_cfg_and_history_only_read_local_evidence(self):
        import tempfile
        c=console()
        with tempfile.TemporaryDirectory() as tmp:
            cfg=Path(tmp)/"cfg.bin"
            raw=bytearray(336);raw[57]=42;cfg.write_bytes(raw)
            c.cfg_flash=cfg
            c.log_path=Path(tmp)/"trace.log"
            c.log_path.write_text(
                "E62_P0_EVENT seq=1 vns=0 kind=DSHOT a=0 b=0 c=0 d=0 e=0 f=0\\n"
                "E62_P0_EVENT seq=2 vns=1 kind=THROT_SET a=1 b=1 c=100 d=1 e=0 f=0\\n")
            with redirect_stdout(io.StringIO()) as out:
                c.do_show("cfg")
                c.do_get("cfg.telem_poles")
                c.do_history("2")
            self.assertIn("SIM_ONLY_PREBOOT_CFG_IMAGE",out.getvalue())
            self.assertIn("cfg.telem_poles = 42",out.getvalue())
            self.assertIn("THROT_SET",out.getvalue())

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
