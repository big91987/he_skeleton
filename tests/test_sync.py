import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from sync_project import sync

class SyncBoundary(unittest.TestCase):
    def test_preserves_application_and_refuses_managed_edits(self):
        source=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d);(dest/'.git').mkdir();(dest/'app').mkdir()
            page=dest/'app/index.html';page.write_text('business code')
            sync(source,dest,'HEAD')
            sync(source,dest,'HEAD')
            self.assertEqual(page.read_text(),'business code')
            managed=dest/'harness/agent.py';managed.write_text('local modification')
            with self.assertRaisesRegex(ValueError,'Local changes'):
                sync(source,dest,'HEAD')
            self.assertEqual(managed.read_text(),'local modification')
