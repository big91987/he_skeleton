import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from full_harness import light
from full_harness.common import controls, read_json, write_json


def result(**changes):
    return dict(next_state="requirements", message="回复", artifacts=[]) | changes


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
            return result(message="问题的回答"), "same"

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
            result(artifacts=["prd.md"]),
            "",
            None,
        )
        pending = self.state["documents"]["requirements"]
        light.apply_result(
            self.session, self.state, result(message="解释范围"), "为什么", None
        )
        self.assertEqual(self.state["documents"]["requirements"], pending)

    def test_approval_and_next_stage_work_in_same_result(self):
        light.apply_result(
            self.session,
            self.state,
            result(artifacts=["prd.md"]),
            "",
            None,
        )
        (self.root / "design.md").write_text("设计")
        light.apply_result(
            self.session,
            self.state,
            result(
                next_state="design",
                artifacts=["design.md"],
            ),
            "没问题，继续",
            None,
        )
        self.assertEqual(self.state["stage"], "design")
        self.assertIn("design", self.state["documents"])
        self.assertIn("requirements", self.state["approvals"])

    def test_cannot_advance_without_message_or_after_artifact_change(self):
        light.apply_result(
            self.session,
            self.state,
            result(artifacts=["prd.md"]),
            "",
            None,
        )
        with self.assertRaises(ValueError):
            light.apply_result(
                self.session, self.state, result(next_state="design"), "", None
            )
        (self.root / "prd.md").write_text("范围 B")
        with self.assertRaises(ValueError):
            light.apply_result(
                self.session,
                self.state,
                result(next_state="design"),
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
                result(next_state="done"),
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
                result(next_state="done", artifacts=["validation.md"])
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
        self.assertEqual(self.state["stage"], "done")
        self.assertNotIn("delivered", self.state)
        self.assertNotIn("status", self.state)

    def test_stale_comment_cannot_approve_newer_document(self):
        light.apply_result(
            self.session,
            self.state,
            result(artifacts=["prd.md"]),
            "",
            None,
        )
        with self.assertRaises(ValueError):
            light.apply_result(
                self.session,
                self.state,
                result(next_state="design"),
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
        first = result(artifacts=["prd.md"])
        light.apply_result(self.session, self.state, first, "", None)
        original = self.state["documents"]["requirements"]["shown_at"]
        light.apply_result(self.session, self.state, first, "解释一下", None)
        self.assertEqual(self.state["documents"]["requirements"]["shown_at"], original)

    def test_invalid_result_does_not_change_state(self):
        import copy

        before = copy.deepcopy(self.state)
        for invalid in (
            {},
            result(next_state="unknown"),
            result(message=None),
            result(status="ready"),
        ):
            with self.assertRaises(ValueError):
                light.apply_result(self.session, self.state, invalid, "继续", None)
            self.assertEqual(self.state, before)

    def test_clarification_and_blocked_messages_need_no_extra_states(self):
        for message in (
            "搜索是否需要区分大小写？",
            "当前无法连接测试环境，请提供地址。",
        ):
            light.apply_result(
                self.session, self.state, result(message=message), "继续", None
            )
            self.assertEqual(self.state["stage"], "requirements")
            self.assertEqual(self.state["reply"], message)
            self.assertNotIn("status", self.state)
            self.assertNotIn("pending", self.state)

    def test_legacy_state_keeps_documents_and_session_without_legacy_flags(self):
        self.state.update(
            pending={
                "stage": "requirements",
                "files": {"prd.md": "abc"},
                "requested_at": "2026-01-01T00:00:00+00:00",
            },
            delivered=False,
            session_id="same",
            status="ready",
        )
        light.migrate(self.state)
        self.assertEqual(self.state["stage"], "requirements")
        self.assertEqual(self.state["session_id"], "same")
        self.assertEqual(
            self.state["documents"]["requirements"]["files"], {"prd.md": "abc"}
        )
        self.assertFalse(
            set(self.state) & {"status", "pending", "delivered", "reply_token"}
        )

    def test_design_approval_can_finish_development_in_same_call(self):
        from full_harness.common import digest

        self.state.update(stage="design", turn=1)
        (self.root / "design.md").write_text("设计")
        light.apply_result(
            self.session,
            self.state,
            result(next_state="design", artifacts=["design.md"]),
            "展示设计",
            None,
        )
        write_json(
            self.session / "turns/1/gate.json",
            {"status": "passed", "snapshot": digest(self.root)},
        )
        light.apply_result(
            self.session,
            self.state,
            result(next_state="done"),
            "设计没问题，完成开发",
            None,
        )
        self.assertEqual(self.state["stage"], "done")
        self.assertIn("design", self.state["approvals"])

    def test_codex_wrapper_accepts_three_field_schema(self):
        from full_harness.codex import invoke

        sid = "00000000-0000-4000-8000-000000000001"
        expected = result(message="是否需要搜索？")

        def process(argv, workspace, env, log, timeout, prompt, stream):
            write_json(Path(argv[argv.index("--output-last-message") + 1]), expected)
            log.write_text(
                __import__("json").dumps({"type": "thread.started", "thread_id": sid})
                + "\n"
            )
            return 0

        with (
            patch(
                "full_harness.codex.runtime_home", return_value=self.session / "home"
            ),
            patch("full_harness.codex.configure_skills"),
            patch("full_harness.codex.run_process", side_effect=process),
        ):
            actual, actual_id = invoke(
                Path.cwd(),
                self.root,
                self.session,
                "需求",
                self.session / "evidence",
                schema_override=light.SCHEMA,
            )
        self.assertEqual(actual, expected)
        self.assertEqual(actual_id, sid)

    def test_transport_failure_preserves_successful_agent_reply_for_retry(self):
        import os

        from full_harness.common import read_json

        self.state.update(
            stage="design", reply="设计完成，请查看。", artifacts=[], run_id="10"
        )
        with (
            patch.dict(os.environ, {"LIGHT_PUBLIC": str(self.session / "public")}),
            patch.object(light, "publish", side_effect=RuntimeError("network")),
        ):
            with self.assertRaises(RuntimeError):
                light.report(self.session, self.state)
        self.assertEqual(self.state["reply"], "设计完成，请查看。")
        with (
            patch.dict(os.environ, {"LIGHT_PUBLIC": str(self.session / "public")}),
            patch.object(light, "publish", return_value="url"),
            patch.object(light, "invoke", side_effect=AssertionError("extra model")),
        ):
            light.report(self.session, self.state)
        self.assertEqual(
            read_json(self.session / "state.json")["reply"], "设计完成，请查看。"
        )

    def test_error_report_does_not_replace_validated_reply(self):
        import os

        self.state.update(reply="研发完成", stage="done", run_id="10", artifacts=[])
        with (
            patch.dict(os.environ, {"LIGHT_PUBLIC": str(self.session / "public")}),
            patch.object(light, "publish", return_value="url"),
        ):
            light.report(self.session, self.state, error="PR 发送失败")
        self.assertEqual(self.state["reply"], "研发完成")
        self.assertIn("PR 发送失败", (self.session / "public/reply.md").read_text())
