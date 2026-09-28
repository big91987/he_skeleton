"""Transport fixtures prove publication/boundaries, not real browser acceptance."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from full_harness.browser import check, serve
from full_harness.common import controls, write_json
from full_harness.screenshots import publish_screenshots


class BrowserDeliveryTests(unittest.TestCase):
    def test_browser_rejects_unconfigured_roots_and_changed_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            work = root / "workspace"
            work.mkdir()
            (work / "AGENTS.md").write_text("Owner rules")
            context = root / "context.json"
            write_json(
                context,
                {
                    "workspace": str(work),
                    "controls": controls(work),
                    "task": {"number": 1},
                    "config": {"browser_roots": ["app"]},
                },
            )
            for args in (
                {"root": "../private", "plan": "plan.json"},
                {"root": "app", "plan": "../private"},
            ):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    check(context, args)
            (work / "AGENTS.md").write_text("Changed rules")
            with self.assertRaisesRegex(ValueError, "Protected"):
                check(context, {"root": "app", "plan": "plan.json"})

    def test_publish_images_recovers_lost_ref_response_and_preserves_visibility(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "workspace").mkdir()
            image = root / "workspace/screen.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            state = {"repo": "a/b", "task": {"number": 1}, "turn": 2}
            remote = {"head": None, "private": False, "commits": 0}

            def api(repo, path, method="GET", data=None):
                if path == "":
                    return {"private": remote["private"]}
                if path.startswith("git/matching-refs"):
                    return (
                        [
                            {
                                "ref": "refs/heads/codex/harness-evidence-1",
                                "object": {"sha": remote["head"]},
                            }
                        ]
                        if remote["head"]
                        else []
                    )
                if path == "git/blobs":
                    return {"sha": "b" * 40}
                if path == "git/trees":
                    return {"sha": "c" * 40}
                if path == "git/commits":
                    remote.update(
                        message=data["message"], commits=remote["commits"] + 1
                    )
                    return {"sha": "a" * 40}
                if path.startswith("git/commits/"):
                    return {"message": remote["message"]}
                if path == "git/refs":
                    remote["head"] = data["sha"]
                    raise RuntimeError("Remote accepted update; response lost")
                raise AssertionError(path)

            with self.assertRaises(RuntimeError):
                publish_screenshots(api, root, state, ["screen.png"], "design")
            body = publish_screenshots(api, root, state, ["screen.png"], "design")
            self.assertIn("📸 截图 · 设计原型", body)
            self.assertIn("![screen.png]", body)
            self.assertIn("a" * 40, body)
            self.assertEqual(remote["commits"], 1)
            remote["private"] = True
            self.assertNotIn(
                "raw.githubusercontent",
                publish_screenshots(api, root, state, ["screen.png"], "design"),
            )
            image.write_text("not PNG")
            with self.assertRaises(ValueError):
                publish_screenshots(api, root, state, ["screen.png"], "design")

    def test_mcp_dispatches_data_plan_and_returns_failed_check_as_error(self):
        import io

        with tempfile.TemporaryDirectory() as temp:
            context = Path(temp) / "context.json"
            write_json(
                context, {"task": {"number": 1}, "config": {"browser_roots": ["app"]}}
            )
            requests = [
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05"},
                },
                {"method": "notifications/initialized"},
                {"id": 2, "method": "tools/list"},
                {
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "check",
                        "arguments": {"root": "app", "plan": "plan.json"},
                    },
                },
            ]
            out = io.StringIO()
            with (
                patch(
                    "sys.stdin", io.StringIO("\n".join(json.dumps(r) for r in requests))
                ),
                patch("sys.stdout", out),
                patch(
                    "full_harness.browser.check", Mock(return_value={"passed": False})
                ) as run,
            ):
                serve(context)
            replies = [json.loads(line) for line in out.getvalue().splitlines()]
            self.assertEqual([r["id"] for r in replies], [1, 2, 3])
            self.assertTrue(replies[-1]["result"]["isError"])
            run.assert_called_once_with(context, {"root": "app", "plan": "plan.json"})
