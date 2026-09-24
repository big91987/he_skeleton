import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from full_harness import runner


class NaturalEntryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.dict(
                os.environ,
                {"GITHUB_ACTIONS": "false", "GITHUB_TRIGGERING_ACTOR": "owner"},
            )
        )
        self.event = {
            "action": "created",
            "sender": {"type": "User"},
            "issue": {"number": 12},
            "comment": {
                "id": 100,
                "body": "为什么要这样设计？",
                "created_at": "2030-01-02T00:00:00Z",
            },
        }
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "workspace").mkdir()
        (self.root / "workspace/prd.md").write_text("Approved version")
        self.state = {
            "repo": "owner/repo",
            "task": {"number": 12, "title": "Feature", "body": "Feature"},
            "stage": "requirements",
            "status": "running",
            "runner": "machine",
            "baseline": "sha",
            "completed": {"requirements": {"artifact": "prd.md"}},
            "turn": 0,
            "config": {"stages": {"requirements": {"skills": []}}},
        }
        runner.request_approval(self.root, self.state, "requirements")
        self.state["pending_approval"]["requested_at"] = "2030-01-01T00:00:00+00:00"

    def message(self, intent, text="为什么要这样设计？", quote=""):
        result = {
            "status": "ready",
            "summary": "Agent 的回答",
            "question": "",
            "intent": intent,
            "approval_quote": quote,
        }
        with patch.object(runner, "respond", return_value=result):
            return runner.handle_message(
                self.root,
                self.root,
                self.state,
                text,
                self.event,
                "sha",
                "machine",
                "next",
            )

    def test_owner_issue_starts_without_label(self):
        event = {"action": "opened", "issue": {"number": 12, "labels": []}}
        self.assertEqual(
            runner.event_input(event, "owner/repo", "owner", "issues"), (12, "")
        )

    def test_natural_comment_and_legacy_newline(self):
        self.assertEqual(
            runner.event_input(self.event, "owner/repo", "owner", "issue_comment"),
            (12, "为什么要这样设计？"),
        )
        self.event["comment"]["body"] = "/develop\n"
        self.assertEqual(
            runner.event_input(self.event, "owner/repo", "owner", "issue_comment"),
            (12, ""),
        )

    def test_permission_levels_and_triggering_actor(self):
        for permission in ["write", "maintain", "admin"]:
            with (
                self.subTest(permission=permission),
                patch.object(runner, "api", return_value={"permission": permission}),
                patch.dict(os.environ, {"GITHUB_TRIGGERING_ACTOR": "developer"}),
            ):
                self.assertEqual(
                    runner.event_input(
                        self.event, "owner/repo", "developer", "issue_comment"
                    )[0],
                    12,
                )
        for permission in ["read", "triage", "none"]:
            with (
                self.subTest(permission=permission),
                patch.object(runner, "api", return_value={"permission": permission}),
            ):
                with self.assertRaises(ValueError):
                    runner.event_input(
                        self.event, "owner/repo", "visitor", "issue_comment"
                    )
        with (
            patch.dict(os.environ, {"GITHUB_TRIGGERING_ACTOR": "visitor"}),
            patch.object(runner, "api", return_value={"permission": "read"}),
        ):
            with self.assertRaises(ValueError):
                runner.event_input(self.event, "owner/repo", "owner", "issue_comment")

    def test_bots_and_prs_never_enter(self):
        self.event["sender"]["type"] = "Bot"
        with self.assertRaises(ValueError):
            runner.event_input(self.event, "owner/repo", "owner", "issue_comment")
        self.event["sender"]["type"] = "User"
        self.event["issue"]["pull_request"] = {}
        with self.assertRaises(ValueError):
            runner.event_input(self.event, "owner/repo", "owner", "issue_comment")

    def test_question_keeps_pending_version(self):
        pending = copy.deepcopy(self.state["pending_approval"])
        self.assertFalse(self.message("answer"))
        self.assertEqual(self.state["status"], "awaiting_approval")
        self.assertEqual(self.state["pending_approval"], pending)
        self.assertEqual(self.state.get("approvals", {}), {})

    def test_natural_approval_without_token_advances(self):
        self.assertTrue(
            self.message(
                "approve", "这版需求确认通过，继续下一阶段。", "这版需求确认通过"
            )
        )
        self.assertIn("requirements", self.state["approvals"])
        self.assertEqual(self.state["stage"], "design")

    def test_continue_is_not_approval(self):
        self.assertFalse(self.message("continue", "继续看看"))
        self.assertEqual(self.state["status"], "awaiting_approval")

    def test_approval_needs_actual_quote_and_current_version(self):
        self.assertFalse(self.message("approve", "能解释一下吗", "我批准了"))
        self.event["comment"]["created_at"] = "2029-01-01T00:00:00Z"
        self.assertFalse(self.message("approve", "批准当前版本", "批准当前版本"))
        self.assertNotIn("requirements", self.state.get("approvals", {}))

    def test_changed_material_cannot_be_approved(self):
        (self.root / "workspace/prd.md").write_text("Changed after review request")
        with self.assertRaisesRegex(ValueError, "Documents changed"):
            self.message("approve", "批准当前版本", "批准当前版本")

    def test_change_reopens_stage_without_approving(self):
        self.assertTrue(self.message("change", "补充权限说明"))
        self.assertEqual(self.state["stage"], "requirements")
        self.assertEqual(self.state["status"], "running")
        self.assertNotIn("requirements", self.state["completed"])

    def test_pause_does_not_start_work(self):
        self.assertFalse(self.message("pause", "先暂停"))
        self.assertEqual(self.state["status"], "paused")

    def test_read_only_turn_cannot_change_files(self):
        def bad(*args):
            (self.root / "workspace/changed.txt").write_text("Unexpected mutation")
            return {"intent": "answer"}

        with patch.object(runner, "respond", side_effect=bad):
            with self.assertRaisesRegex(ValueError, "Read-only"):
                runner.handle_message(
                    self.root,
                    self.root,
                    self.state,
                    "问题",
                    self.event,
                    "sha",
                    "machine",
                    "next",
                )
