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

    def test_agent_handoff_accepts_updated_evidence_without_reapproval_gate(self):
        light.apply_result(
            self.session, self.state, result(artifacts=["prd.md"]), "", None
        )
        (self.root / "obsolete.md").write_text("已废弃草稿")
        light.apply_result(
            self.session, self.state, result(artifacts=["obsolete.md"]), "", None
        )
        (self.root / "obsolete.md").unlink()
        (self.root / "prd.md").write_text("范围 A，补齐验证记录")
        (self.root / "evidence.md").write_text("真实补证")
        light.apply_result(
            self.session,
            self.state,
            result(
                next_state="design",
                message="需求已确认，交给设计",
                artifacts=["evidence.md"],
            ),
            "ok 开始下一阶段",
            "2020-01-01T00:00:00Z",
        )
        self.assertEqual(self.state["stage"], "design")
        handoff = self.state["history"][-1]
        self.assertEqual(handoff["message"], "ok 开始下一阶段")
        self.assertEqual(handoff["reply"], "需求已确认，交给设计")
        self.assertEqual(set(handoff["files"]), {"prd.md", "evidence.md"})

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
                "source": str(Path.cwd()),
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
        # Legacy approval hashes are trace data in light, not a hidden hook gate.
        self.state["approvals"] = {"requirements": {"files": {"prd.md": "old-hash"}}}
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
                "source": str(Path.cwd()),
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

    def test_stage_session_recovery_and_legacy_adoption_do_not_cross_stages(self):
        import json
        import uuid

        requirement_id, design_id = str(uuid.uuid4()), str(uuid.uuid4())
        write_json(self.session / "codex-session.json", {"session_id": requirement_id})
        sid, requirement_record = light.stage_session(self.session, "requirements")
        self.assertEqual(sid, requirement_id)
        self.assertEqual(light.stage_session(self.session, "design")[0], None)
        # Simulate a hard cancellation after native thread.started, before checkpoint save.
        evidence = self.session / "turns/3"
        write_json(evidence / "context.json", {"stage_session": "design"})
        (evidence / "agent").mkdir()
        (evidence / "agent/agent.jsonl").write_text(
            json.dumps({"type": "thread.started", "thread_id": design_id}) + "\n"
        )
        sid, design_record = light.stage_session(self.session, "design")
        self.assertEqual(sid, design_id)
        self.assertEqual(read_json(design_record)["session_id"], design_id)
        self.assertEqual(
            light.stage_session(self.session, "requirements")[0], requirement_id
        )
        self.assertEqual(read_json(requirement_record)["session_id"], requirement_id)
        self.assertEqual(light.stage_session(self.session, "development")[0], None)
        write_json(design_record, {"session_id": requirement_id})
        with self.assertRaisesRegex(ValueError, "Session"):
            light.stage_session(self.session, "design")

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
        self.assertEqual(self.state["history"][-1]["from"], "design")

    def test_codex_wrapper_accepts_three_field_schema(self):
        from full_harness.codex import invoke
        from full_harness.common import clean_env

        for policy in (
            {"unset": ["PATH"]},
            {"inherit": "NODE_PATH"},
            {"set": {"APP_MODE": None}},
            {"inherit": ["GH_TOKEN"]},
            {"set": {"CODEX_HOME": "other"}},
        ):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                clean_env(policy)
        sid = "00000000-0000-4000-8000-000000000001"
        expected = result(message="是否需要搜索？")

        forwarded = []

        def process(argv, workspace, env, log, timeout, prompt, stream, on_event):
            self.assertEqual(env.get("NODE_PATH"), "/runner/browser/node_modules")
            self.assertEqual(env["APP_MODE"], "test")
            self.assertEqual(env["HTTP_PROXY"], "")
            self.assertNotIn("GH_TOKEN", env)
            on_event({"type": "turn.started"})
            write_json(Path(argv[argv.index("--output-last-message") + 1]), expected)
            log.write_text(
                __import__("json").dumps({"type": "thread.started", "thread_id": sid})
                + "\n"
            )
            return 0

        with (
            patch.dict(
                "os.environ",
                {
                    "NODE_PATH": "/runner/browser/node_modules",
                    "GH_TOKEN": "private",
                    "APP_MODE": "old",
                    "HTTP_PROXY": "http://unused",
                },
            ),
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
                environment={
                    "inherit": ["NODE_PATH", "APP_MODE"],
                    "set": {"APP_MODE": "test", "HTTP_PROXY": ""},
                },
                on_event=forwarded.append,
                session_record=self.session / "agents/requirements/codex-session.json",
            )
        self.assertEqual(forwarded, [{"type": "turn.started"}])
        self.assertEqual(actual, expected)
        self.assertEqual(actual_id, sid)
        self.assertEqual(
            read_json(self.session / "agents/requirements/codex-session.json")[
                "session_id"
            ],
            sid,
        )
        self.assertFalse((self.session / "codex-session.json").exists())

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
        events = [
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {
                    "id": "item_3",
                    "type": "agent_message",
                    "text": json.dumps(raw, ensure_ascii=False),
                },
            },
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        ]
        (turn / "agent/agent.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n"
        )
        with (
            patch.dict(os.environ, {"LIGHT_PUBLIC": str(self.session / "public")}),
            patch.object(light, "publish", return_value="url"),
            patch.object(light, "invoke", side_effect=AssertionError("extra model")),
        ):
            light.report(self.session, self.state)
        body = html.unescape((self.session / "public/reply.md").read_text())
        self.assertTrue(body.startswith("[codex] 设计完成\n\n[harness] "))
        self.assertIn("[harness] 本轮阶段", body)
        self.assertIn("[harness] [运行日志及产物下载]", body)
        self.assertIn("requirements → design", body)
        self.assertIn('"type": "item.completed"', body)
        self.assertIn('"type": "turn.completed"', body)
        self.assertIn("本轮执行：已结束", body)
        self.assertEqual(
            json.loads((self.session / "public/agent-events.json").read_text()), events
        )
        self.assertEqual(
            json.loads((self.session / "public/agent-result.json").read_text()), raw
        )
        # Even after saving a forward transition, an actual error must be visible.
        with (
            patch.dict(os.environ, {"LIGHT_PUBLIC": str(self.session / "public")}),
            patch.object(light, "publish", return_value="url") as publish,
        ):
            light.report(
                self.session, self.state, error="交接执行失败", continuous=True
            )
        self.assertIn("交接执行失败", publish.call_args.args[2])

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
        self.assertTrue(body.startswith("[harness] 校验未通过"))
        self.assertIn('"next_state": "done"', body)
        self.assertEqual(self.state["stage"], "requirements")
        self.assertEqual(self.state["reply"], "原回复")

    def test_failed_turn_does_not_show_previous_turn_output(self):
        import json
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
        failed = {"type": "turn.failed", "error": {"message": "connection closed"}}
        log = self.session / "turns/2/agent/agent.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps(failed) + "\n")
        with (
            patch.dict(os.environ, {"LIGHT_PUBLIC": str(self.session / "public")}),
            patch.object(light, "publish", return_value="url"),
        ):
            light.report(self.session, self.state, error="连接失败")
        self.assertEqual(read_json(self.session / "public/agent-events.json"), [failed])
        self.assertFalse((self.session / "public/agent-result.json").exists())

    def test_conversation_modes_reload_checkpoint_resume_and_publish_once(self):
        for continuous in (False, True):
            with self.subTest(continuous=continuous):
                self.conversation(continuous)

    def conversation(self, continuous):
        """Fake only Codex/GitHub; exercise the actual entry, disk state and replies."""
        import hashlib
        import json
        import os

        source = self.session / ("source-wait" if continuous else "source-once")
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
        inbox = []
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
        private = self.session / ("private-wait" if continuous else "private-once")
        scope = hashlib.sha256(b"test/repo\0main").hexdigest()[:16]
        session = private / "light" / scope / "1"

        def github(repo, path, method="GET", data=None):
            if path == "issues/1":
                finished = (session / "state.json").exists() and read_json(
                    session / "state.json"
                )["turn"] >= 7
                return {
                    **task,
                    "state": "closed" if continuous and finished else "open",
                }
            if method == "POST":
                replies.append(data["body"])
                return {"id": len(replies)}
            if method == "PATCH":
                comment_id = int(path.rsplit("/", 1)[1])
                replies[comment_id - 1] = data["body"]
                return {"id": comment_id}
            if path.startswith("issues/1/comments?"):
                return inbox
            raise AssertionError(path)

        def codex(source, workspace, home, prompt, evidence, **options):
            current = read_json(evidence.parent / "context.json")["state"]["stage"]
            self.assertEqual(options["skills"], [current])
            self.assertEqual(
                options["hook_context"] is not None, current == "development"
            )
            self.assertEqual(
                options["session_id"],
                current + "-session" if options["session_record"].exists() else None,
            )
            self.assertNotIn("SKILL_BODY_NOT_FOR_PROMPT", prompt)
            packet = json.loads(prompt.split("\n", 1)[1])
            if current != "development":
                self.assertNotIn("artifact", packet["stage_instructions"])
            else:
                self.assertIn("artifact", packet["stage_instructions"])
            if (
                continuous
                and read_json(evidence.parent / "context.json")["state"]["turn"] == 1
            ):
                self.assertEqual(packet["message"], "已接收但尚未执行的评论")
            if packet["handoff"]:
                self.assertNotEqual(packet["handoff"]["from"], current)
                self.assertIn("reply", packet["handoff"])
                self.assertTrue(packet["handoff"]["files"])
                self.assertEqual(packet["handoff"]["to"], current)
                if options["session_id"] is None:
                    self.assertEqual(packet["message"], "")
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
            write_json(options["session_record"], {"session_id": current + "-session"})
            self.assertEqual(options["session_record"].parent.name, current)
            # Replies become visible only after this turn's final publication.
            return output, current + "-session"

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
            if continuous:
                write_json(
                    event_file,
                    {"issue": task, "sender": {"type": "User"}, "action": "opened"},
                )
                os.environ["GITHUB_RUN_ID"] = "one-run"
                messages = iter(
                    ["大小写呢？", "再看看文档", "ok 继续吧", "设计没问题，开始实现"]
                )

                def user_reply(_seconds):
                    from datetime import datetime, timezone

                    inbox.append(
                        {
                            "id": 1000 + len(inbox),
                            "body": next(messages),
                            "user": {"type": "User", "login": "test"},
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )

                with patch.object(light.time, "sleep", side_effect=user_reply):
                    route = light.main("restore", wait_seconds=60)
                    self.assertEqual(agent.call_count, 0)
                    self.assertEqual(route, "requirements")
                    checkpoint = read_json(session / "state.json")
                    checkpoint["conversation_input"] = {
                        "id": "accepted-before-cancel",
                        "message": "已接收但尚未执行的评论",
                        "sent": None,
                    }
                    write_json(session / "state.json", checkpoint)
                    write_json(
                        event_file,
                        {"sender": {"type": "User"}, "inputs": {"task": "1"}},
                    )
                    os.environ["GITHUB_EVENT_NAME"] = "workflow_dispatch"
                    os.environ["GITHUB_RUN_ID"] = "resumed-run"
                    self.assertEqual(
                        light.main("restore", wait_seconds=60), "requirements"
                    )
                    route = light.main(route, wait_seconds=60)
                    self.assertEqual(route, "design")
                    saved = read_json(session / "state.json")
                    original_document = saved["documents"]["requirements"]
                    self.assertEqual(saved["turn"], 4)
                    # Retrying the finished Job republishes no history and calls no model.
                    self.assertEqual(
                        light.main("requirements", wait_seconds=60), "design"
                    )
                    self.assertEqual(agent.call_count, 4)
                    self.assertEqual(light.main("restore", wait_seconds=60), "design")
                    route = light.main(route, wait_seconds=60)
                    self.assertEqual(route, "development")
                    route = light.main(route, wait_seconds=60)
                    self.assertEqual(route, "")
                saved = read_json(session / "state.json")
                self.assertEqual(saved["documents"]["requirements"], original_document)
                self.assertEqual(
                    saved["session_id"],
                    (
                        "development"
                        if saved["stage"] == "development"
                        else "design"
                        if saved["stage"] == "design"
                        else "requirements"
                    )
                    + "-session",
                )
                self.assertEqual(saved["run_id"], "resumed-run")
                self.assertEqual(saved["turn"], 7)
                self.assertEqual(saved["history"][0]["message"], "ok 继续吧")
                self.assertEqual(saved["history"][-1]["from"], "design")
                final_replies = [
                    r for r in replies if "<!-- harness-event:progress:" not in r
                ]
                self.assertFalse(
                    any(
                        "需求已确认，接着设计" in r or "设计已确认，接着开发" in r
                        for r in final_replies
                    )
                )
                for turn in (4, 6):
                    archive = self.session / "public/turns" / str(turn)
                    self.assertTrue((archive / "agent-result.json").is_file())
                    self.assertTrue((archive / "reply.md").is_file())
                self.assertEqual(agent.call_count, 7)
                self.assertEqual(len(replies), 12)
                self.assertEqual(
                    len(list((self.session / "public/turns").iterdir())), 7
                )
            else:
                for index, message in enumerate(
                    [
                        None,
                        "大小写呢？",
                        "再看看文档",
                        "ok 继续吧",
                        "设计没问题，开始实现",
                    ],
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
                    self.assertEqual(
                        saved["session_id"],
                        (
                            "development"
                            if saved["stage"] == "development"
                            else "design"
                            if saved["stage"] == "design"
                            else "requirements"
                        )
                        + "-session",
                    )
                    self.assertFalse(set(saved) & {"status", "pending", "delivered"})
                    if index == 1:
                        original_document = saved["documents"]["requirements"]
                    self.assertEqual(
                        saved["documents"]["requirements"], original_document
                    )
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
                self.assertEqual(saved["history"][0]["message"], "ok 继续吧")
                self.assertIn("design", saved["documents"])
                self.assertEqual(saved["history"][-1]["from"], "design")
                self.assertIn("环境暂不可用", replies[-1])
                route = light.main("restore")
                while route in light.STAGES:
                    route = light.main(route)
                self.assertEqual(agent.call_count, 7)
                self.assertEqual(len(replies), 14)
                self.assertEqual(read_json(session / "state.json"), saved)

    def test_waiting_inbox_permissions_pagination_restart_and_timeout(self):
        import time
        from datetime import datetime, timezone

        def comment(number, actor="visitor", kind="User"):
            return {
                "id": number,
                "body": "继续",
                "user": {"login": actor, "type": kind},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        comments = [comment(n, kind="Bot") for n in range(1, 101)]
        comments += [comment(101), comment(102, "test"), comment(103, "test")]
        self.state["handled"] = ["102:requirements"]

        def github(repo, path, method="GET", data=None):
            if path == "issues/1":
                return {"state": "open"}
            if path == "collaborators/visitor/permission":
                return {"permission": "read"}
            page = int(path.rsplit("=", 1)[1])
            return comments[(page - 1) * 100 : page * 100]

        with patch.object(light, "api", side_effect=github):
            incoming = light.wait_for_reply(
                self.session, self.state, time.monotonic() + 10, 0
            )
            self.assertEqual(incoming["id"], "103")
            restored = read_json(self.session / "state.json")
            self.assertEqual(restored["comment_cursor"], 103)
            self.assertEqual(restored["conversation_input"], incoming)
            with self.assertRaises(TimeoutError):
                light.wait_for_reply(self.session, restored, time.monotonic() + 0.01, 0)
        with patch.object(light, "api", return_value={"state": "closed"}):
            self.assertIsNone(
                light.wait_for_reply(self.session, restored, time.monotonic() + 10, 0)
            )
        self.assertEqual(read_json(self.session / "state.json"), restored)

    def test_waiting_survives_transient_get_failures_without_consuming_input(self):
        import subprocess
        import time

        from full_harness import runner

        state = self.state
        state["comment_cursor"] = 100
        comment = {
            "id": 101,
            "body": "继续核对设计",
            "created_at": "2026-09-28T00:00:00Z",
            "user": {"login": "developer", "type": "User"},
        }
        calls = {}

        def github_process(argv, **kwargs):
            path = argv[2]
            count = calls[path] = calls.get(path, 0) + 1
            if count == 1:
                self.assertEqual(state["comment_cursor"], 100)
                if path.endswith("issues/1"):
                    return subprocess.CompletedProcess(
                        argv,
                        1,
                        "",
                        'Get "https://api.github.com/repos/test/repo/issues/1": EOF\n',
                    )
                if "comments?" in path:
                    raise subprocess.TimeoutExpired(argv, 90)
                return subprocess.CompletedProcess(
                    argv, 1, "", "HTTP 503: Service Unavailable"
                )
            if count == 2 and path.endswith("issues/1"):
                return subprocess.CompletedProcess(argv, 1, "", "unexpected EOF")
            body = (
                {"state": "open"}
                if path.endswith("issues/1")
                else [comment]
                if "comments?" in path
                else {"permission": "write"}
            )
            return subprocess.CompletedProcess(
                argv, 0, __import__("json").dumps(body), ""
            )

        with (
            patch.object(runner.subprocess, "run", side_effect=github_process),
            patch.object(light.time, "sleep"),
        ):
            incoming = light.wait_for_reply(
                self.session, state, time.monotonic() + 2, 0
            )
        self.assertEqual(incoming["id"], "101")
        self.assertEqual(
            read_json(self.session / "state.json")["conversation_input"], incoming
        )
        self.assertEqual(state["comment_cursor"], 101)
        for method, failure in (
            ("GET", "HTTP 403: Forbidden"),
            ("GET", "HTTP 403: EOF"),
            ("POST", "unexpected EOF"),
            (
                "POST",
                'Post "https://api.github.com/repos/test/repo/issues/1/comments": EOF',
            ),
        ):
            with (
                self.subTest(method=method),
                patch.object(
                    runner.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 1, "", failure),
                ) as command,
            ):
                with self.assertRaises(RuntimeError) as caught:
                    runner.api("test/repo", "issues/1/comments", method)
                self.assertNotIsInstance(caught.exception, runner.GitHubReadUnavailable)
                self.assertEqual(command.call_count, 1)
