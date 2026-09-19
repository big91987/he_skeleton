import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from update_project import MANAGED, TEMPLATES, prepare

class UpdateProject(unittest.TestCase):
    def test_pinned_sync_preserves_business_and_rejects_drift(self):
        with tempfile.TemporaryDirectory() as folder:
            source, product = Path(folder)/'source', Path(folder)/'product'
            product.mkdir()
            for name in [*MANAGED, *TEMPLATES.values()]:
                path=source/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('upstream')
            (product/'app').mkdir(); (product/'app/index.html').write_text('business')
            changes=prepare(source,product,'canonical-remote-sha')
            self.assertEqual(set(changes),set(MANAGED)|set(TEMPLATES)|{'harness-upstream.json'})
            for name, data in changes.items():
                path=product/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(data)
            self.assertEqual(prepare(source,product,'canonical-remote-sha'),{})
            self.assertEqual(json.loads((product/'harness-upstream.json').read_text())['revision'],'canonical-remote-sha')
            (product/MANAGED[0]).write_text('product customization')
            with self.assertRaisesRegex(ValueError,'Local changes'):
                prepare(source,product,'new-sha')
            self.assertEqual((product/'app/index.html').read_text(),'business')
