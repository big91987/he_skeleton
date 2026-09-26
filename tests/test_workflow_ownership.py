import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from sync_project import MANAGED, TEMPLATES, sync
from update_project import prepare


class WorkflowOwnership(unittest.TestCase):
    def test_install_upgrade_and_legacy_migration_on_both_paths(self):
        for transport in ("local", "remote"):
            with (
                self.subTest(transport=transport),
                tempfile.TemporaryDirectory() as folder,
            ):
                source, product = Path(folder) / "source", Path(folder) / "product"
                source.mkdir()
                product.mkdir()
                (product / ".git").mkdir()
                for name in [*MANAGED, *TEMPLATES.values()]:
                    p = source / name
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("upstream-v1")

                def commit():
                    for args in (
                        ["git", "init", "-q"],
                        ["git", "add", "."],
                        [
                            "git",
                            "-c",
                            "user.name=Test",
                            "-c",
                            "user.email=test@example.invalid",
                            "-c",
                            "core.hooksPath=/dev/null",
                            "commit",
                            "-qm",
                            "fixture",
                        ],
                    ):
                        subprocess.run(
                            args, cwd=source, check=True, capture_output=True
                        )

                def install():
                    if transport == "local":
                        return sync(source, product, "HEAD")
                    changes = prepare(source, product, "fixture-sha")
                    for name, data in changes.items():
                        p = product / name
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_text(data)
                    return list(changes)

                commit()
                # An existing Owner workflow must survive even the first install.
                workflow, form = list(TEMPLATES)
                p = product / workflow
                p.parent.mkdir(parents=True)
                p.write_text("owner-flow")
                installed = install()
                self.assertNotIn(workflow, installed)
                self.assertIn(form, installed)  # bootstrap must stage the seeded form
                self.assertEqual((product / workflow).read_text(), "owner-flow")
                self.assertEqual((product / form).read_text(), "upstream-v1")
                self.assertEqual(
                    set(
                        json.loads((product / "harness-upstream.json").read_text())[
                            "files"
                        ]
                    ),
                    set(MANAGED),
                )
                # Simulate the old manifest that claimed both templates as managed.
                m = product / "harness-upstream.json"
                legacy = json.loads(m.read_text())
                for name in TEMPLATES:
                    legacy["files"][name] = hashlib.sha256(b"old-template").hexdigest()
                m.write_text(json.dumps(legacy))
                # Owner renamed the workflow and edited the form, upstream changed both.
                (product / workflow).rename(product / ".github/workflows/custom.yml")
                (product / form).write_text("owner-form")
                for name in [*MANAGED, *TEMPLATES.values()]:
                    (source / name).write_text("upstream-v2")
                commit()
                changed = install()
                self.assertFalse((product / workflow).exists())
                self.assertEqual(
                    (product / ".github/workflows/custom.yml").read_text(), "owner-flow"
                )
                self.assertEqual((product / form).read_text(), "owner-form")
                self.assertEqual((product / MANAGED[0]).read_text(), "upstream-v2")
                self.assertTrue(set(changed).isdisjoint(TEMPLATES))
                self.assertEqual(set(json.loads(m.read_text())["files"]), set(MANAGED))
                (product / form).unlink()
                install()
                self.assertFalse(
                    (product / form).exists()
                )  # intentional deletion stays deleted
                if transport == "local":
                    before = {
                        str(p.relative_to(product)): p.read_bytes()
                        for p in product.rglob("*")
                        if p.is_file()
                    }
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        self.assertEqual(sync(source, product, "HEAD", True), [])
                    self.assertIn("upstream-template/", output.getvalue())
                    self.assertEqual(
                        before,
                        {
                            str(p.relative_to(product)): p.read_bytes()
                            for p in product.rglob("*")
                            if p.is_file()
                        },
                    )
