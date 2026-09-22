import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from full_harness.common import run_process

class LiveOutputTests(unittest.TestCase):
    def test_output_arrives_before_exit_and_raw_log_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);log=root/'agent.jsonl';seen=threading.Event()
            class Console(io.StringIO):
                def write(self,text):
                    result=super().write(text)
                    if 'first-event' in text:seen.set()
                    return result
            console=Console();result=[]
            script='import time; print("first-event",flush=True); time.sleep(1); print("::error::literal",flush=True)'
            with contextlib.redirect_stdout(console):
                t=threading.Thread(target=lambda:result.append(run_process([sys.executable,'-c',script],root,None,log,5,stream=True)))
                t.start()
                try:
                    self.assertTrue(seen.wait(.8),'output must arrive while child is running')
                    self.assertTrue(t.is_alive())
                finally:t.join(6)
            self.assertEqual(result,[0])
            self.assertEqual(log.read_text(),'first-event\n::error::literal\n')
            self.assertIn('[codex] ::error::literal',console.getvalue())
    def test_timeout_retains_output_and_stops_stream(self):
        with tempfile.TemporaryDirectory() as d:
            log=Path(d)/'agent.jsonl';console=io.StringIO()
            with contextlib.redirect_stdout(console):
                with self.assertRaises(subprocess.TimeoutExpired):
                    run_process([sys.executable,'-c','import time; print("before-timeout",flush=True); time.sleep(30)'],d,None,log,.4,stream=True)
            self.assertIn('before-timeout',console.getvalue())
            self.assertEqual(log.read_text(),'before-timeout\n')
    def test_default_output_remains_private(self):
        with tempfile.TemporaryDirectory() as d:
            console=io.StringIO()
            with contextlib.redirect_stdout(console):
                code=run_process([sys.executable,'-c','print("private")'],d,None,Path(d)/'log',5)
            self.assertEqual(code,0);self.assertEqual(console.getvalue(),'')
