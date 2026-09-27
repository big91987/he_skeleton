import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from full_harness import light
from full_harness.common import controls, read_json, write_json


def result(**changes):
    return (
        dict(
            status="ready",
            summary="回复",
            question="",
            artifacts=[],
            stage="requirements",
            awaiting_approval=False,
            delivered=False,
            approval_quote="",
        )
        | changes
    )


class LightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = Path(self.temp.name)
        self.root = self.session / "workspace"
        self.root.mkdir()
        (self.root / "prd.md").write_text("范围 A")
        self.state = {
            "stage": "requirements",
            "status": "ready",
            "turn": 0,
            "task": {"number": 1, "body": "做一个工具"},
            "repo": "test/repo",
            "controls": controls(self.root),
            "config": {
                "entries": [],
                "agent_timeout": 60,
                "stages": {s: {"skills": [], "instruction": s} for s in light.STAGES},
            },
        }

    def test_one_call_per_message_and_resume_with_union_of_skills(self):
        calls = []

        def invoke(*args, **kwargs):
            calls.append(kwargs)
            args[4].mkdir(parents=True)
            write_json(self.session / "codex-session.json", {"session_id": "same"})
            return result(summary="问题的回答"), "same"

        with patch.object(light, "invoke", side_effect=invoke):
            light.execute(Path.cwd(), self.session, self.state, "解释一下", "1")
            light.execute(Path.cwd(), self.session, self.state, "再解释一下", "2")
        self.assertEqual(len(calls), 2)
        self.assertIsNone(calls[0]["session_id"])
        self.assertEqual(calls[1]["session_id"], "same")
        self.assertEqual(self.state["reply"], "问题的回答")
        with patch.object(light, "invoke", side_effect=AssertionError("duplicate")):
            light.execute(Path.cwd(), self.session, self.state, "再解释一下", "2")
        self.assertEqual(self.state["turn"], 2)

    def test_question_preserves_pending_artifact(self):
        light.apply_result(
            self.session,
            self.state,
            result(artifacts=["prd.md"], awaiting_approval=True),
            "",
            None,
        )
        pending = self.state["pending"]
        light.apply_result(
            self.session, self.state, result(summary="解释范围"), "为什么", None
        )
        self.assertEqual(self.state["pending"], pending)

    def test_approval_and_next_stage_work_in_same_result(self):
        light.apply_result(
            self.session,
            self.state,
            result(artifacts=["prd.md"], awaiting_approval=True),
            "",
            None,
        )
        (self.root / "design.md").write_text("设计")
        light.apply_result(
            self.session,
            self.state,
            result(
                stage="design",
                approval_quote="没问题",
                artifacts=["design.md"],
                awaiting_approval=True,
            ),
            "没问题，继续",
            None,
        )
        self.assertEqual(self.state["stage"], "design")
        self.assertEqual(self.state["pending"]["stage"], "design")
        self.assertIn("requirements", self.state["approvals"])

    def test_cannot_advance_without_user_quote_or_after_artifact_change(self):
        light.apply_result(
            self.session,
            self.state,
            result(artifacts=["prd.md"], awaiting_approval=True),
            "",
            None,
        )
        with self.assertRaises(ValueError):
            light.apply_result(
                self.session, self.state, result(stage="design"), "为什么", None
            )
        (self.root / "prd.md").write_text("范围 B")
        with self.assertRaises(ValueError):
            light.apply_result(
                self.session,
                self.state,
                result(stage="design", approval_quote="同意"),
                "同意",
                None,
            )
        self.assertEqual(self.state["stage"], "requirements")

    def test_delivery_requires_matching_real_gate(self):
        self.state["stage"] = "development"
        self.state["turn"] = 2
        with self.assertRaises(ValueError):
            light.apply_result(
                self.session,
                self.state,
                result(stage="development", delivered=True),
                "继续",
                None,
            )

    def test_document_hook_does_not_run_development_checks(self):
        from full_harness.light_hook import evaluate

        context = self.session / "context.json"
        write_json(
            context,
            {
                "state": self.state,
                "workspace": str(self.root),
                "session": str(self.session),
                "evidence": str(self.session / "evidence"),
            },
        )
        with patch(
            "full_harness.light_hook.development_check",
            side_effect=AssertionError("not development"),
        ):
            self.assertEqual(
                evaluate(
                    context,
                    {"last_assistant_message": __import__("json").dumps(result())},
                ),
                {},
            )
        self.assertFalse((self.session / "evidence/gate.json").exists())

    def test_failed_call_is_not_silently_reexecuted_on_retry(self):
        with patch.object(light, "invoke", side_effect=RuntimeError("connection lost")):
            with self.assertRaises(RuntimeError):
                light.execute(Path.cwd(), self.session, self.state, "继续", "1")
        persisted = read_json(self.session / "state.json")
        with patch.object(light, "invoke", side_effect=AssertionError("duplicate")):
            with self.assertRaises(RuntimeError):
                light.execute(Path.cwd(), self.session, persisted, "继续", "1")

    def test_development_hook_runs_real_check_and_blocks_then_passes_without_model(
        self,
    ):
        import json
        import sys
        import time

        from full_harness.light_hook import evaluate

        self.state.update(stage="development", turn=1)
        (self.root / "validation.md").write_text("实际验证记录")
        self.state["config"].update(
            max_attempts=3,
            check_timeout=10,
            checks=[
                {
                    "name": "real functional check",
                    "argv": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; assert Path('fixed.txt').exists(), 'repair required'",
                    ],
                }
            ],
        )
        self.state["config"]["stages"]["development"]["artifact"] = "validation.md"
        evidence = self.session / "turns/1"
        evidence.mkdir(parents=True)
        context = evidence / "context.json"
        write_json(
            context,
            {
                "state": self.state,
                "workspace": str(self.root),
                "session": str(self.session),
                "evidence": str(evidence),
                "message": "继续",
                "sent": None,
                "config": self.state["config"],
                "controls": self.state["controls"],
                "stage": "development",
                "task": self.state["task"],
                "deadline_monotonic": time.monotonic() + 60,
            },
        )
        payload = {
            "last_assistant_message": json.dumps(
                result(stage="development", delivered=True, artifacts=["validation.md"])
            )
        }
        with patch(
            "full_harness.stop_hook.invoke",
            side_effect=AssertionError("extra model call"),
        ):
            self.assertEqual(evaluate(context, payload)["decision"], "block")
            (self.root / "fixed.txt").write_text("repaired")
            self.assertEqual(evaluate(context, payload), {})
        gate = read_json(evidence / "gate.json")
        self.assertEqual(gate["status"], "passed")
        self.assertEqual(gate["attempts"], 2)
        self.assertIn("repair required", (evidence / "check-1-0.log").read_text())
        light.apply_result(
            self.session,
            self.state,
            json.loads(payload["last_assistant_message"]),
            "继续",
            None,
        )
        self.assertTrue(self.state["delivered"])

    def test_stale_comment_cannot_approve_newer_document(self):
        light.apply_result(
            self.session,
            self.state,
            result(artifacts=["prd.md"], awaiting_approval=True),
            "",
            None,
        )
        with self.assertRaises(ValueError):
            light.apply_result(
                self.session,
                self.state,
                result(stage="design", approval_quote="同意"),
                "同意",
                "2020-01-01T00:00:00Z",
            )

    def test_invalid_artifact_cannot_escape_workspace(self):
        with self.assertRaises(ValueError):
            light.apply_result(
                self.session,
                self.state,
                result(artifacts=["../private.json"]),
                "",
                None,
            )

    def test_repeated_pending_version_keeps_original_confirmation_time(self):
        first = result(artifacts=["prd.md"], awaiting_approval=True)
        light.apply_result(self.session, self.state, first, "", None)
        original = self.state["pending"]["requested_at"]
        light.apply_result(self.session, self.state, first, "解释一下", None)
        self.assertEqual(self.state["pending"]["requested_at"], original)
