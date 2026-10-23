#!/usr/bin/env python3
"""Offline E62 trace viewer contract; no web services or simulated motor PASS."""
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

VIEWER = Path(__file__).resolve().parents[1] / "web" / "sitl_trace_viewer.html"


class ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inline = []
        self.external = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            props = dict(attrs)
            if "src" in props:
                self.external.append(props["src"])
            else:
                self.in_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.inline.append(data)


class TestOfflineViewer(unittest.TestCase):
    def test_local_only_and_explicit_no_edge_waveform_claim(self):
        html = VIEWER.read_text(encoding="utf-8")
        p = ScriptParser()
        p.feed(html)
        self.assertFalse(p.external, "Offline viewer must not load CDN JS")
        self.assertEqual(len(p.inline), 1)
        self.assertIn("measured carrier-average duty at WFI checkpoints", html)
        self.assertIn("not individual PWM pin transitions", html)
        self.assertIn("SIM_ONLY", html)
        self.assertIn("CAP1_ACCEPTED", html)
        self.assertIn("TIMG12_SERVICED", html)
        self.assertIn("No Guest control", html)

    @unittest.skipUnless(shutil.which("node"), "Node syntax checker unavailable")
    def test_inline_browser_javascript_is_syntactically_valid(self):
        parser = ScriptParser()
        parser.feed(VIEWER.read_text(encoding="utf-8"))
        proc = subprocess.run(["node", "--check", "-"],
                              input="\n".join(parser.inline),
                              text=True,capture_output=True,check=False)
        self.assertEqual(proc.returncode,0,proc.stderr)


if __name__=="__main__":
    unittest.main(verbosity=2)
