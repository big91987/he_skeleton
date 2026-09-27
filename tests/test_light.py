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

    def test_design_approval_hands_off_to_development_job(self):
        self.state.update(stage="design", turn=1)
        (self.root / "design.md").write_text("设计")
        light.apply_result(
            self.session,
            self.state,
            result(next_state="design", artifacts=["design.md"]),
            "展示设计",
            None,
        )
        with self.assertRaises(ValueError):
            light.apply_result(
                self.session, self.state, result(next_state="done"), "设计没问题", None
            )
        light.apply_result(
            self.session,
            self.state,
            result(next_state="development"),
            "设计没问题",
            None,
        )
        self.assertEqual(self.state["stage"], "development")
        self.assertIn("design", self.state["approvals"])

    def test_codex_wrapper_accepts_three_field_schema(self):
        from full_harness.codex import invoke

        sid = "00000000-0000-4000-8000-000000000001"
        expected = result(message="是否需要搜索？")

        forwarded = []

        def process(argv, workspace, env, log, timeout, prompt, stream, on_event):
            on_event({"type": "turn.started"})
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
                on_event=forwarded.append,
            )
        self.assertEqual(forwarded, [{"type": "turn.started"}])
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

    def test_report_shows_actual_output_and_checkpoint_without_another_model(self):
        import html
        import json
        import os

        self.state.update(
            stage="design", turn=2, reply="设计完成", run_id="10", artifacts=[]
        )
        turn = self.session / "turns/2"
        write_json(turn / "context.json", {"state": {"stage": "requirements"}})
        raw = result(next_state="design", message="设计完成", artifacts=[])
        write_json(turn / "agent/result.json", raw)
        with (
            patch.dict(os.environ, {"LIGHT_PUBLIC": str(self.session / "public")}),
            patch.object(light, "publish", return_value="url"),
            patch.object(light, "invoke", side_effect=AssertionError("extra model")),
        ):
            light.report(self.session, self.state)
        body = html.unescape((self.session / "public/reply.md").read_text())
        self.assertIn("requirements → design", body)
        self.assertIn('"next_state": "design"', body)
        self.assertIn('"artifacts": []', body)
        self.assertNotIn('"message":', body)
        self.assertEqual(
            json.loads((self.session / "public/agent-fields.json").read_text()),
            {"next_state": "design", "artifacts": []},
        )

    def test_rejected_result_shows_proposal_separately_from_saved_stage(self):
        import html
        import os

        self.state.update(
            stage="requirements", turn=2, reply="原回复", run_id="10", artifacts=[]
        )
        turn = self.session / "turns/2"
        write_json(turn / "context.json", {"state": {"stage": "requirements"}})
        write_json(turn / "agent/result.json", result(next_state="done"))
        with (
            patch.dict(os.environ, {"LIGHT_PUBLIC": str(self.session / "public")}),
            patch.object(light, "publish", return_value="url"),
        ):
            light.report(self.session, self.state, error="校验未通过")
        body = html.unescape((self.session / "public/reply.md").read_text())
        self.assertIn("requirements → requirements", body)
        self.assertIn('"next_state": "done"', body)
        self.assertEqual(self.state["stage"], "requirements")
        self.assertEqual(self.state["reply"], "原回复")

    def test_failed_turn_does_not_show_previous_turn_output(self):
        import os

        self.state.update(
            stage="requirements", turn=2, reply="原回复", run_id="10", artifacts=[]
        )
        write_json(
            self.session / "turns/1/agent/result.json", result(next_state="design")
        )
        with (
            patch.dict(os.environ, {"LIGHT_PUBLIC": str(self.session / "public")}),
            patch.object(light, "publish", return_value="url"),
        ):
            light.report(self.session, self.state, error="连接失败")
        body = (self.session / "public/reply.md").read_text()
        self.assertIn("本轮未取得可解析的 Agent 结构化输出", body)
        self.assertNotIn("next_state", body)

    def test_issue_conversation_reloads_checkpoint_resumes_and_publishes_once(self):
        """Fake only Codex/GitHub; exercise the actual entry, disk state and replies."""
        import hashlib
        import json
        import os

        source = self.session / "source"
        source.mkdir()
        cfg = {"version": 2, "entries": [], "stages": {}}
        for stage in light.STAGES:
            skill = source / "full_harness/skills" / stage / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("SKILL_BODY_NOT_FOR_PROMPT")
            cfg["stages"][stage] = {
                "skills": [stage],
                "review_skills": [],
                "artifact": stage + ".md",
            }
        cfg["stages"]["review"] = {"skills": []}
        write_json(source / ".harness/full.json", cfg)
        task = {"number": 1, "title": "搜索", "body": "按书名搜索"}
        replies = []
        outputs = iter(
            [
                result(message="请确认需求", artifacts=["prd.md"]),
                result(message="搜索不需要区分大小写"),
                result(message="这是同一份需求", artifacts=["prd.md"]),
                result(next_state="design", message="需求已确认，接着设计"),
                result(
                    next_state="design", message="设计已完成", artifacts=["design.md"]
                ),
                result(next_state="development", message="设计已确认，接着开发"),
                result(next_state="development", message="环境暂不可用，保留现场"),
            ]
        )
        private = self.session / "private"
        scope = hashlib.sha256(b"test/repo\0main").hexdigest()[:16]
        session = private / "light" / scope / "1"

        def github(repo, path, method="GET", data=None):
            if path == "issues/1":
                return {**task, "state": "open"}
            if method == "POST":
                replies.append(data["body"])
                return {"id": len(replies)}
            if method == "PATCH":
                comment_id = int(path.rsplit("/", 1)[1])
                replies[comment_id - 1] = data["body"]
                return {"id": comment_id}
            if path.startswith("issues/1/comments?"):
                return []
            raise AssertionError(path)

        def codex(source, workspace, home, prompt, evidence, **options):
            current = read_json(evidence.parent / "context.json")["state"]["stage"]
            self.assertEqual(options["skills"], [current])
            self.assertEqual(
                options["hook_context"] is not None, current == "development"
            )
            self.assertEqual(
                options["session_id"],
                "same-session" if (home / "codex-session.json").exists() else None,
            )
            self.assertNotIn("SKILL_BODY_NOT_FOR_PROMPT", prompt)
            output = next(outputs)
            before = len(replies)
            stream = options["on_event"]
            stream(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "p1",
                        "type": "agent_message",
                        "text": "开始核对现有文件",
                    },
                }
            )
            self.assertEqual(len(replies), before + 1)
            stream(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "p2",
                        "type": "agent_message",
                        "text": json.dumps(result(message="发现需要核对的接口")),
                    },
                }
            )
            stream(
                {
                    "type": "item.started",
                    "item": {
                        "id": "tool",
                        "type": "command_execution",
                        "command": "PRIVATE_TOOL_CONTENT",
                    },
                }
            )
            self.assertEqual(len(replies), before + 1)
            self.assertIn("<details>", replies[-1])
            self.assertIn("开始核对现有文件", replies[-1])
            self.assertIn("发现需要核对的接口", replies[-1])
            self.assertNotIn("PRIVATE_TOOL_CONTENT", replies[-1])
            stream(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "final",
                        "type": "agent_message",
                        "text": json.dumps(output),
                    },
                }
            )
            stream({"type": "turn.completed"})
            self.assertEqual(len(replies), before + 1)
            for name in output["artifacts"]:
                (workspace / name).write_text("unchanged " + name)
            write_json(evidence / "result.json", output)
            write_json(home / "codex-session.json", {"session_id": "same-session"})
            return output, "same-session"

        event_file = self.session / "event.json"
        env = {
            "GITHUB_EVENT_PATH": str(event_file),
            "GITHUB_REPOSITORY": "test/repo",
            "GITHUB_ACTOR": "test",
            "GITHUB_TRIGGERING_ACTOR": "test",
            "GITHUB_EVENT_NAME": "issues",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": "baseline",
            "RUNNER_NAME": "fixture",
            "FULL_STATE_ROOT": str(private),
            "LIGHT_PUBLIC": str(self.session / "public"),
            "GITHUB_ACTIONS": "false",
            "GITHUB_STEP_SUMMARY": "",
        }
        with (
            patch.dict(os.environ, env),
            patch.object(light, "__file__", str(source / "full_harness/light.py")),
            patch.object(light, "api", side_effect=github),
            patch.object(light, "invoke", side_effect=codex) as agent,
        ):
            for index, message in enumerate(
                [None, "大小写呢？", "再看看文档", "ok 继续吧", "设计没问题，开始实现"],
                1,
            ):
                event = {
                    "issue": task,
                    "sender": {"type": "User"},
                    "action": "opened" if index == 1 else "created",
                }
                if message is not None:
                    event["comment"] = {"id": index, "body": message}
                write_json(event_file, event)
                os.environ["GITHUB_EVENT_NAME"] = (
                    "issues" if index == 1 else "issue_comment"
                )
                os.environ["GITHUB_RUN_ID"] = str(index)
                calls_before = agent.call_count
                route = light.main("restore")
                self.assertEqual(
                    agent.call_count, calls_before
                )  # disk routing, no model
                while route in light.STAGES:
                    route = light.main(route)
                saved = read_json(session / "state.json")
                expected_calls = index if index < 4 else 2 * index - 3
                self.assertEqual(saved["turn"], expected_calls)
                self.assertEqual(saved["session_id"], "same-session")
                self.assertFalse(set(saved) & {"status", "pending", "delivered"})
                if index == 1:
                    original_document = saved["documents"]["requirements"]
                self.assertEqual(saved["documents"]["requirements"], original_document)
                self.assertEqual(
                    saved["stage"],
                    "development"
                    if index == 5
                    else "design"
                    if index == 4
                    else "requirements",
                )
                self.assertEqual(agent.call_count, expected_calls)
                self.assertEqual(len(replies), 2 * expected_calls)
            self.assertEqual(saved["approvals"]["requirements"]["message"], "ok 继续吧")
            self.assertIn("design", saved["documents"])
            self.assertIn("design", saved["approvals"])
            self.assertIn("环境暂不可用", replies[-1])
            route = light.main("restore")
            while route in light.STAGES:
                route = light.main(route)
            self.assertEqual(agent.call_count, 7)
            self.assertEqual(len(replies), 14)
            self.assertEqual(read_json(session / "state.json"), saved)
