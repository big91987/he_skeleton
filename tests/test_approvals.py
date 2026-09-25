import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from full_harness import runner
from full_harness.common import controls, digest


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        # Unit fixtures must not publish checkpoints from the surrounding CI job.
        self.enterContext(patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / "workspace"
        self.work.mkdir()
        for name in ["prd.md", "design.md", "contract.json"]:
            (self.work / name).write_text("accepted " + name)
        self.state = {
            "runner": "machine",
            "baseline": "sha",
            "run_id": "1",
            "repo": "owner/repo",
            "task": {"number": 1},
            "stage": "requirements",
            "status": "running",
            "completed": {},
            "history": [],
            "turn": 0,
            "controls": controls(self.work),
            "config": {
                "entries": [],
                "stages": {
                    s: {"skills": [], "artifact": s + ".md"} for s in runner.STAGES[:3]
                },
            },
        }
        self.state["completed"]["requirements"] = {
            "artifact": "prd.md",
            "summary": "PRD ready",
        }

    def approve(self, stage):
        runner.request_approval(self.root, self.state, stage)
        token = self.state["reply_token"]
        runner.begin(self.state, token + " approve", "sha", "machine", "2", self.root)

    def test_approval_advances_only_after_explicit_confirmation(self):
        runner.request_approval(self.root, self.state, "requirements")
        self.assertEqual(self.state["status"], "awaiting_approval")
        token = self.state["reply_token"]
        with self.assertRaises(ValueError):
            runner.begin(self.state, "old approve", "sha", "machine", "2", self.root)
        runner.begin(self.state, token + " approve", "sha", "machine", "2", self.root)
        self.assertEqual(self.state["stage"], "design")
        self.assertIn("requirements", self.state["approvals"])

    def test_feedback_reopens_same_stage_not_approval(self):
        runner.request_approval(self.root, self.state, "requirements")
        token = self.state["reply_token"]
        runner.begin(
            self.state, token + " add permissions", "sha", "machine", "2", self.root
        )
        self.assertEqual(self.state["stage"], "requirements")
        self.assertNotIn("requirements", self.state.get("approvals", {}))
        self.assertNotIn("requirements", self.state["completed"])

    def test_clarification_answer_is_not_confirmation(self):
        self.state["status"] = "needs_input"
        self.state["reply_token"] = "token"
        runner.begin(self.state, "token approve", "sha", "machine", "2", self.root)
        self.assertEqual(self.state["stage"], "requirements")
        self.assertNotIn("requirements", self.state.get("approvals", {}))

    def test_changed_document_cannot_use_old_confirmation(self):
        runner.request_approval(self.root, self.state, "requirements")
        token = self.state["reply_token"]
        (self.work / "prd.md").write_text("different scope")
        with self.assertRaises(ValueError):
            runner.begin(
                self.state, token + " approve", "sha", "machine", "2", self.root
            )
        self.assertNotIn("requirements", self.state.get("approvals", {}))

    def test_all_declared_contracts_bound_to_confirmation(self):
        self.approve("requirements")
        self.state["completed"]["design"] = {
            "artifact": "design.md",
            "artifacts": ["design.md", "contract.json"],
        }
        self.approve("design")
        self.assertEqual(self.state["stage"], "development")
        (self.work / "contract.json").write_text("new contract")
        self.assertEqual(runner.changed_approval(self.root, self.state), "design")

    def test_reused_documents_still_require_human_confirmation(self):
        self.state["completed"]["requirements"] = {
            "mode": "reuse",
            "evidence": {"prd.md": "hash"},
            "summary": "reuse PRD",
        }
        with patch.object(
            runner, "invoke", side_effect=AssertionError("Do not regenerate reused PRD")
        ):
            runner.run_agent(self.root, self.root, self.state, "requirements")
        self.assertEqual(self.state["status"], "awaiting_approval")
        self.assertIn("prd.md", self.state["pending_approval"]["files"])

    def test_development_cannot_start_without_both_approvals(self):
        with self.assertRaises(ValueError):
            runner.development(self.root, self.root, self.state)
        self.approve("requirements")
        with self.assertRaises(ValueError):
            runner.development(self.root, self.root, self.state)

    def test_development_runs_all_internal_steps_without_human_stop(self):
        self.approve("requirements")
        self.state["completed"]["design"] = {"artifact": "design.md"}
        self.approve("design")
        calls = []

        def advance(name, next_stage):
            def fn(*args):
                calls.append(name)
                self.state["stage"] = next_stage

            return fn

        def delivered(*args):
            calls.append("delivery")
            self.state["status"] = "waiting_review"

        with (
            patch.object(
                runner, "run_agent", side_effect=advance("development", "verification")
            ),
            patch.object(
                runner, "verify_stage", side_effect=advance("verification", "review")
            ),
            patch.object(
                runner, "review_stage", side_effect=advance("review", "delivery")
            ),
            patch.object(runner, "deliver", side_effect=delivered),
        ):
            runner.development(self.root, self.root, self.state)
        self.assertEqual(calls, ["development", "verification", "review", "delivery"])

    def test_independent_review_cannot_auto_accept_design_revision(self):
        self.approve("requirements")
        self.state["completed"]["design"] = {"artifact": "design.md"}
        self.approve("design")
        self.state["config"].update(max_attempts=2, review_timeout=10)
        self.state["completed"]["verification"] = {"snapshot": digest(self.work)}

        def author(*args):
            stage = args[-1]
            self.state["completed"][stage] = {"artifact": "design.md"}
            runner.request_approval(self.root, self.state, stage)

        result = {
            "status": "changes",
            "return_stage": "design",
            "summary": "revise contract",
            "findings": ["missing field"],
        }
        with (
            patch.object(runner, "review_prompt", return_value="review"),
            patch.object(runner, "invoke", return_value=(result, "reviewer")),
            patch.object(runner, "run_agent", side_effect=author),
        ):
            runner.review_stage(self.root, self.root, self.state)
        self.assertEqual(self.state["status"], "awaiting_approval")
        self.assertEqual(self.state["stage"], "design")
        self.assertNotIn("design", self.state["approvals"])

    def test_delivery_block_resume_reopens_changed_approved_document(self):
        self.approve("requirements")
        self.state["completed"]["design"] = {"artifact": "design.md"}
        self.approve("design")
        self.state.update(stage="delivery", status="blocked", reply_token="recovery")
        (self.work / "prd.md").write_text("new requirements")
        runner.begin(self.state, "recovery continue", "sha", "machine", "3", self.root)

        def author(*args):
            self.assertEqual(args[-1], "requirements")
            self.state["completed"]["requirements"] = {"artifact": "prd.md"}
            runner.request_approval(self.root, self.state, "requirements")

        with (
            patch.object(runner, "run_agent", side_effect=author),
            patch.object(
                runner, "deliver", side_effect=AssertionError("must reapprove first")
            ),
        ):
            runner.development(self.root, self.root, self.state)
        self.assertEqual(self.state["status"], "awaiting_approval")
        self.assertEqual(self.state["stage"], "requirements")
        self.assertNotIn("design", self.state.get("approvals", {}))

    def test_report_displays_confirmation_and_all_contracts(self):
        self.state["completed"]["design"] = {
            "artifact": "design.md",
            "artifacts": ["design.md", "contract.json"],
        }
        runner.request_approval(self.root, self.state, "design")
        with patch.object(runner, "api", return_value={"id": 1}):
            runner.report(self.root, self.state)
        text = (self.root / "public/status.md").read_text()
        self.assertIn("直接评论", text)
        self.assertIn("contract.json", text)
        self.assertTrue((self.root / "public/design/contract.json").is_file())

    def test_reporting_never_edits_existing_issue_history(self):
        self.state["comment_id"] = 777
        self.state["last_reply"] = "Initial answer"
        with patch.object(runner, "api", return_value={"id": 100}) as api:
            runner.report(self.root, self.state)
            runner.report(self.root, self.state)
            self.state["last_reply"] = "Correction after checking"
            runner.report(self.root, self.state)
        methods = [c.args[2] for c in api.call_args_list if len(c.args) > 2]
        self.assertEqual(methods, ["POST", "POST"])
        self.assertFalse(
            any("issues/comments/777" in c.args[1] for c in api.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
