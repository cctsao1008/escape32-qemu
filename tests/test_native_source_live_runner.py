#!/usr/bin/env python3
"""Host-only tests: external probe wrapper never steps or writes Guest QTest."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_source_live_runner import watch_log
from tools.native_source_trace import NativeSourceReducer, FORMAT
from tools.sitl_live import LiveTelemetryHub, SitlLiveServer
from tests.test_native_source_trace import fixture,line

class TestNoWfiLiveAdapter(unittest.TestCase):
    def test_tail_sees_real_log_append_and_publishes_source_packets(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"qemu.log"
            rows=fixture()
            script=("from pathlib import Path;import time\n"
                    f"p=Path({str(path)!r})\n"
                    f"rows={list(map(line,rows))!r}\n"
                    "with p.open('w') as f:\n"
                    "  for item in rows:\n"
                    "    f.write(item);f.flush();time.sleep(0.002)\n")
            proc=subprocess.Popen([sys.executable,"-c",script])
            hub=LiveTelemetryHub(capacity=4)
            hub.begin(NativeSourceReducer().metadata)
            errors=[]
            try:
                summary=watch_log(path,proc,hub,errors,poll_s=0.005)
                self.assertEqual(proc.wait(timeout=3),0)
                self.assertEqual(errors,[])
                self.assertEqual(summary["observed_source_events"],10)
                self.assertEqual(summary["observed_samples"],2)
                snap=hub.snapshot()
                self.assertEqual(snap["seq"],2)
                self.assertEqual(snap["metadata"]["format"],FORMAT)
                self.assertEqual(snap["packets"][0]["sample"]["motor_rpm"],123.456)
                self.assertEqual(snap["packets"][1]["sample"]["cap1_count"],1)
                self.assertNotIn("pwm_duties",snap["packets"][0]["sample"])
            finally:
                if proc.poll() is None:
                    proc.kill();proc.wait(timeout=3)
                hub.close()
    def test_source_sse_reuses_local_readonly_hub(self):
        hub=LiveTelemetryHub(capacity=3)
        server=SitlLiveServer(port=0,hub=hub).start()
        try:
            hub.begin(NativeSourceReducer().metadata)
            r=NativeSourceReducer()
            frames=[x for e in fixture() if (x:=r.ingest(e)) is not None]
            for f in frames:
                hub.publish(f["sample"],f["events"])
            with urlopen(server.url+"events",timeout=3) as response:
                self.assertEqual(response.readline().decode().strip(),
                                 "event: snapshot")
                snap=json.loads(response.readline().decode()[6:])
                self.assertEqual(snap["metadata"]["format"],FORMAT)
                self.assertEqual(snap["seq"],2)
                self.assertEqual(snap["packets"][0]["sample"]["bemf_codes"],
                                 [2001,2012,2023])
                self.assertTrue(snap["read_only"])
        finally:
            server.close()
    def test_source_adapter_errors_dont_become_probe_motor_pass(self):
        hub=LiveTelemetryHub(capacity=2)
        hub.begin(NativeSourceReducer().metadata)
        hub.finish(native_result={"probe_exit_code":1},
                   error_type="NativeProbeFailed")
        self.assertEqual(hub.snapshot()["complete"]["strict_extended_gate"],
                         "NOT_EXECUTED_BY_LIVE_TELEMETRY")
        self.assertEqual(hub.snapshot()["complete"]["error_type"],
                         "NativeProbeFailed")

if __name__=="__main__":
    unittest.main(verbosity=2)
