import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from sync_project import sync, MANAGED, TEMPLATES

class SyncBoundary(unittest.TestCase):
    def test_preserves_application_and_refuses_managed_edits(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as d:
            source=Path(src)
            for name in [*MANAGED, *TEMPLATES.values()]:
                p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('managed fixture')
            for command in [['git','init','-q'],['git','add','.'],['git','-c','user.name=Test','-c','user.email=test@example.invalid','-c','core.hooksPath=/dev/null','commit','-qm','fixture']]:
                subprocess.run(command,cwd=source,check=True,capture_output=True)
            dest=Path(d);(dest/'.git').mkdir();(dest/'app').mkdir()
            page=dest/'app/index.html';page.write_text('business code')
            sync(source,dest,'HEAD')
            sync(source,dest,'HEAD')
            self.assertEqual(page.read_text(),'business code')
            managed=dest/'harness/agent.py';managed.write_text('local modification')
            with self.assertRaisesRegex(ValueError,'Local changes'):
                sync(source,dest,'HEAD')
            self.assertEqual(managed.read_text(),'local modification')
