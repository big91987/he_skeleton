import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))
import loop


class TrustAndRecovery(unittest.TestCase):
    def event(self, user="owner", body="/harness 请加筛选"):
        return {
            "repository": {"owner": {"login": "owner"}},
            "sender": {"login": user},
            "comment": {"body": body, "id": 42},
            "issue": {"number": 7},
        }

    def test_nonowner_cannot_trigger(self):
        with self.assertRaises(PermissionError):
            loop.command(self.event("stranger"), "issue_comment")

    def test_plain_conversation_does_not_trigger(self):
        with self.assertRaises(ValueError):
            loop.command(self.event(body="please execute this"), "issue_comment")

    def test_prefix_collision_rejected(self):
        with self.assertRaises(ValueError):
            loop.command(self.event(body="/harness-bypass"), "issue_comment")

    def test_multiline_feedback_and_stable_event_id(self):
        self.assertEqual(
            loop.command(self.event(body="/harness 修改\n继续"), "issue_comment"),
            (7, "修改\n继续", "comment-42"),
        )

    def test_checkpoint_survives_new_reader(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            loop.atomic(p, {"status": "waiting_input", "history": [{"user": "先问我"}]})
            self.assertEqual(json.loads(p.read_text())["history"][0]["user"], "先问我")
            self.assertFalse(p.with_suffix(".tmp").exists())

    def test_preview_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "index.html").write_text("ok")
            (root / "leak.txt").symlink_to("/etc/hosts")
            with self.assertRaises(ValueError):
                loop.app_files(root)

    def test_preview_rejects_secret_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "index.html").write_text("ok")
            (root / ".env").write_text("secret")
            with self.assertRaises(ValueError):
                loop.app_files(root)

    def test_code_publisher_does_not_overwrite_new_remote_head(self):
        calls = []

        def fake(method, path, body=None):
            calls.append((method, path, body))
            if "/git/ref/heads/" in path:
                return {"object": {"sha": "latest-head"}}
            if "/git/commits/latest-head" in path:
                return {"tree": {"sha": "tree"}}
            if "?recursive=1" in path:
                return {"tree": []}
            if path.endswith("/git/blobs"):
                return {"sha": "blob"}
            if path.endswith("/git/trees"):
                return {"sha": "new-tree"}
            if path.endswith("/git/commits"):
                return {"sha": "new-commit"}
            return {}

        with patch.object(loop, "gh", side_effect=fake):
            with self.assertRaisesRegex(RuntimeError, "Branch changed"):
                loop.publish_code(
                    "o/r", "codex/task-7", "old-base", {"index.html": b"ok"}, "update"
                )
            loop.publish_code(
                "o/r", "codex/task-7", "latest-head", {"index.html": b"ok"}, "update"
            )
        commit = next(c[2] for c in calls if c[1].endswith("/git/commits"))
        self.assertEqual(commit["parents"], ["latest-head"])
        self.assertFalse(calls[-1][2]["force"])


class EventDelivery(unittest.TestCase):
    def test_redelivered_completed_event_does_not_call_agent_or_github(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            event = {
                "repository": {"owner": {"login": "owner"}, "full_name": "owner/repo"},
                "sender": {"login": "owner"},
                "comment": {"body": "/harness 继续", "id": 42},
                "issue": {"number": 7},
            }
            event_file = root / "event.json"
            event_file.write_text(json.dumps(event))
            session = root / "sessions/7"
            session.mkdir(parents=True)
            loop.atomic(
                session / "state.json",
                {"processed": ["comment-42"], "history": [], "round": 1},
            )
            env = {
                "GITHUB_EVENT_PATH": str(event_file),
                "GITHUB_EVENT_NAME": "issue_comment",
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_RUN_ID": "100",
                "HARNESS_ROOT": str(root),
                "RUNNER_TEMP": str(root / "tmp"),
            }
            with (
                patch.dict(os.environ, env),
                patch.object(loop, "gh") as api,
                patch.object(loop, "run_agent") as agent,
            ):
                loop.main()
                api.assert_not_called()
                agent.assert_not_called()

    def test_fork_pr_is_rejected_before_workspace_import_or_agent(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            event = {
                "repository": {"owner": {"login": "owner"}, "full_name": "owner/repo"},
                "sender": {"login": "owner"},
                "comment": {"body": "/harness 检查", "id": 43},
                "issue": {"number": 8},
            }
            p = root / "event.json"
            p.write_text(json.dumps(event))
            env = {
                "GITHUB_EVENT_PATH": str(p),
                "GITHUB_EVENT_NAME": "issue_comment",
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_RUN_ID": "101",
                "HARNESS_ROOT": str(root),
                "RUNNER_TEMP": str(root / "tmp"),
            }

            def api(method, path, body=None):
                if "/issues/" in path:
                    return {"state": "open", "pull_request": {}}
                if "/git/ref/" in path:
                    return {"object": {"sha": "abc"}}
                if "/pulls/" in path:
                    return {"head": {"repo": {"full_name": "stranger/repo"}}}
                return {"default_branch": "main"}

            with (
                patch.dict(os.environ, env),
                patch.object(loop, "gh", side_effect=api),
                patch.object(loop, "run_agent") as agent,
            ):
                with self.assertRaises(PermissionError):
                    loop.main()
                agent.assert_not_called()
                self.assertFalse((root / "sessions/8/workspace").exists())


class ClarificationGate(unittest.TestCase):
    def test_new_issue_defaults_to_read_only(self):
        self.assertTrue(
            loop.clarification_only("issues", "先问我", "开始处理上述需求。")
        )

    def test_explicit_direct_entry_and_answer_can_implement(self):
        self.assertFalse(
            loop.clarification_only(
                "issues", "### 开始方式\n\n直接实施", "开始处理上述需求。"
            )
        )
        self.assertFalse(
            loop.clarification_only("issue_comment", "先问我", "保留，继续实现")
        )

    def test_explicit_clarify_command_is_read_only(self):
        self.assertTrue(
            loop.clarification_only("issue_comment", "", "clarify 先看范围")
        )


class PublishRecovery(unittest.TestCase):
    def test_publish_restores_result_without_model_or_code_change(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            session = root / "sessions/7"
            session.mkdir(parents=True)
            preview = root / "previews/task-7/round-2"
            preview.mkdir(parents=True)
            (preview / "index.html").write_text("verified product")
            loop.atomic(
                session / "state.json",
                {
                    "processed": [],
                    "history": [{"agent": {"summary": "done"}}],
                    "round": 2,
                    "preview": "task-7/round-2",
                    "pr_url": "https://example.test/pr",
                    "source_sha": "verified-sha",
                },
            )
            event = {
                "repository": {"owner": {"login": "owner"}, "full_name": "owner/repo"},
                "sender": {"login": "owner"},
                "comment": {"body": "/harness publish", "id": 44},
                "issue": {"number": 7},
            }
            p = root / "event.json"
            p.write_text(json.dumps(event))
            env = {
                "GITHUB_EVENT_PATH": str(p),
                "GITHUB_EVENT_NAME": "issue_comment",
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_RUN_ID": "102",
                "HARNESS_ROOT": str(root),
                "RUNNER_TEMP": str(root / "tmp"),
                "GITHUB_OUTPUT": str(root / "output"),
            }
            with (
                patch.dict(os.environ, env),
                patch.object(loop, "gh") as api,
                patch.object(loop, "run_agent") as agent,
            ):
                loop.main()
                agent.assert_not_called()
                api.assert_called_once()
            self.assertEqual(
                json.loads((session / "state.json").read_text())["round"], 2
            )
            self.assertEqual(
                json.loads((root / "tmp/harness-output/result.json").read_text())[
                    "sha"
                ],
                "verified-sha",
            )
            self.assertIn("publish=true", (root / "output").read_text())


class ExperimentIsolation(unittest.TestCase):
    def test_distinct_branches_and_main_have_distinct_state_roots(self):
        root = Path("/tmp/harness")
        a, sa = loop.experiment_context(root, "codex/harness-test-a")
        b, sb = loop.experiment_context(root, "codex/harness-test-b")
        self.assertNotEqual(a, b)
        self.assertNotEqual(sa, sb)
        self.assertEqual(loop.experiment_context(root, ""), (root, ""))
        self.assertEqual(loop.experiment_context(root, "codex/harness-test-a"), (a, sa))
        with self.assertRaises(ValueError):
            loop.experiment_context(root, "main")

    def test_stop_on_experiment_does_not_change_main_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            main = root / "sessions/7"
            main.mkdir(parents=True)
            (main / "state.json").write_text("original main state")
            event = {
                "repository": {"owner": {"login": "owner"}, "full_name": "owner/repo"},
                "sender": {"login": "owner"},
                "inputs": {"task": "7", "instruction": "stop"},
            }
            p = root / "event.json"
            p.write_text(json.dumps(event))
            env = {
                "GITHUB_EVENT_PATH": str(p),
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_RUN_ID": "200",
                "HARNESS_ROOT": str(root),
                "RUNNER_TEMP": str(root / "tmp"),
                "HARNESS_EXPERIMENT": "codex/harness-test-a",
            }
            with (
                patch.dict(os.environ, env),
                patch.object(loop, "gh"),
                patch.object(loop, "run_agent") as agent,
            ):
                loop.main()
                agent.assert_not_called()
            self.assertEqual((main / "state.json").read_text(), "original main state")
            scoped, _ = loop.experiment_context(root, env["HARNESS_EXPERIMENT"])
            self.assertEqual(
                json.loads((scoped / "sessions/7/state.json").read_text())["status"],
                "stopped",
            )


if __name__ == "__main__":
    unittest.main()
