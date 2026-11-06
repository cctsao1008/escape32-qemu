"""RR teardown must observe QMP quit acknowledgement before closing."""
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('probe',Path(__file__).with_name('e62_autonomous_native_motor_probe.py'))
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

class Connection:
    def __init__(self,lines):self.stream=io.BytesIO(lines);self.sent=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def settimeout(self,*args):pass
    def connect(self,*args):pass
    def makefile(self,*args):return self.stream
    def sendall(self,data):self.sent.append(data)

class QuitTests(unittest.TestCase):
    def run_quit(self,tail):
        conn=Connection(b'{"QMP":{}}\n{"return":{}}\n'+tail)
        with patch.object(probe.socket,'socket',return_value=conn):
            probe._quit_differential_rr_vm('/unused')
        return conn
    def test_events_are_consumed_until_quit_ack(self):
        c=self.run_quit(b'{"event":"SHUTDOWN"}\n{"return":{}}\n')
        self.assertEqual(c.stream.read(),b'')
        self.assertIn(b'"quit"',c.sent[-1])
    def test_eof_allowed_because_exit_is_independently_checked(self):self.run_quit(b'')
    def test_quit_error_is_not_success(self):
        with self.assertRaises(RuntimeError):self.run_quit(b'{"error":{"class":"CommandNotFound"}}\n')

if __name__=='__main__':unittest.main()
