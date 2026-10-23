#!/usr/bin/env python3
"""Host-only Phase 2 live telemetry tests. Never claims original ELF PASS."""
import json
import socket
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sitl_live import LiveTelemetryHub, SitlLiveServer


def frame(i):
    return {"wfi": i, "t_ns": i*5,
            "pwm_duties": [0,0,0,1,0.1,0.9],
            "motor_rpm": 100-i}


class TestLiveHub(unittest.TestCase):
    def test_bounded_ring_exposes_overrun_and_maintains_order(self):
        hub=LiveTelemetryHub(capacity=2)
        hub.begin({"elf_sha256":"a"*64, "host_guest_register_writes":False})
        for i in range(1,6):
            hub.publish(frame(i), [{"kind":"CAP1_ACCEPTED","sector":i}])
        snap=hub.snapshot()
        self.assertEqual(snap["seq"],5)
        self.assertEqual(snap["oldest_seq"],4)
        self.assertTrue(snap["truncated"])
        self.assertEqual([p["sample"]["wfi"] for p in snap["packets"]],[4,5])
        missed=hub.since(1,timeout=0.01)
        self.assertEqual(missed["missing"],2)
        self.assertEqual([seq for seq,_ in missed["packets"]],[4,5])
        self.assertFalse(snap["metadata"]["host_guest_register_writes"])
        self.assertTrue(snap["read_only"])

    def test_start_end_are_explicit_and_cannot_resume_publishing(self):
        hub=LiveTelemetryHub(capacity=4)
        with self.assertRaisesRegex(RuntimeError,"Missing live session"):
            hub.publish(frame(1),[])
        hub.begin({"elf_sha256":"b"*64})
        hub.publish(frame(1),[])
        hub.finish(native_result={"direction_continuity_qualified_sim_only":False},
                   error_type="RuntimeError")
        self.assertEqual(hub.snapshot()["complete"]["strict_extended_gate"],
                         "NOT_EXECUTED_BY_LIVE_TELEMETRY")
        with self.assertRaisesRegex(RuntimeError,"after SITL completion"):
            hub.publish(frame(2),[])
        hub.close()


class TestLocalHttp(unittest.TestCase):
    def setUp(self):
        self.hub=LiveTelemetryHub(capacity=4)
        self.server=SitlLiveServer(port=0,hub=self.hub).start()

    def tearDown(self):
        self.server.close()

    def test_dashboard_served_without_external_dependencies(self):
        with urlopen(self.server.url, timeout=3) as response:
            body=response.read().decode()
            self.assertIn("E62 SITL Workbench",body)
            self.assertIn("EventSource",body)
            self.assertIn("sampled PWM",body)
            self.assertEqual(response.headers["Cache-Control"],"no-store")
            self.assertIn("connect-src 'self'",
                          response.headers["Content-Security-Policy"])

    def test_localhost_security_and_no_commands(self):
        for req,expected in [
            (Request(self.server.url,data=b"{}",method="POST"),405),
            (Request(self.server.url+"../../hidden"),404),
            (Request(self.server.url,headers={"Host":"attacker.example"}),403),
            (Request(self.server.url,headers={
                "Origin":"https://attacker.example"}),403),
        ]:
            with self.assertRaises(HTTPError) as result:
                urlopen(req,timeout=3)
            self.assertEqual(result.exception.code,expected)

    def test_live_sse_sends_metadata_and_original_wfi_packet(self):
        with urlopen(self.server.url+"events",timeout=3) as response:
            self.assertEqual(response.headers["Content-Type"],
                             "text/event-stream; charset=utf-8")
            # Server sends a first snapshot even before original Guest runs.
            self.assertEqual(response.readline().decode().strip(),
                             "event: snapshot")
            self.assertTrue(response.readline().decode().startswith("data: "))
            self.assertEqual(response.readline(),b"\n")
            self.hub.begin({"elf_sha256":"a"*64})
            self.hub.publish(frame(1),[{"kind":"CAP1_ACCEPTED","sector":1}])
            lines=[]
            for _ in range(12):
                item=response.readline().decode().strip()
                lines.append(item)
                if item.startswith("data: ") and '"wfi":1' in item:
                    break
            self.assertIn("event: begin",lines)
            self.assertIn("event: frame",lines)
            self.assertTrue(any('"CAP1_ACCEPTED"' in x for x in lines))
            self.assertEqual(self.hub.snapshot()["seq"],1)
            self.assertEqual(self.hub.snapshot()["packets"][0]["sample"]["wfi"],1)


if __name__=="__main__":
    unittest.main(verbosity=2)
