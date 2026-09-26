import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from full_harness import quality
from full_harness.common import digest


class PythonQualityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_check_rejects_unformatted_code_without_writing(self):
        (self.root / "app.py").write_text("x=1;print(x)\n")
        before = digest(self.root)
        self.assertEqual(quality.run(self.root, "check"), 1)
        self.assertEqual(digest(self.root), before)
        self.assertEqual(quality.run(self.root, "fix"), 0)
        self.assertEqual(quality.run(self.root, "check"), 0)

    def test_unfixable_undefined_name_still_fails(self):
        (self.root / "app.py").write_text("print(missing_name)\n")
        self.assertEqual(quality.run(self.root, "fix"), 1)

    def test_missing_ruff_is_environment_block(self):
        (self.root / "app.py").write_text('print("ok")\n')
        with patch.object(quality.shutil, "which", return_value=None):
            self.assertEqual(quality.run(self.root, "check"), 125)

    def test_no_business_python_does_not_require_ruff(self):
        runtime = self.root / "full_harness"
        runtime.mkdir()
        (runtime / "runner.py").write_text("runtime=1\n")
        (self.root / "main.go").write_text("package main\n")
        self.assertEqual(quality.checks(self.root), [])
        with patch.object(quality.shutil, "which", side_effect=AssertionError):
            self.assertEqual(quality.run(self.root, "check"), 0)
