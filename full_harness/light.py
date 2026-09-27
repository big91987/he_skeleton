#!/usr/bin/env python3
"""One user message, one native Codex execution; no classifier or model reviewer."""

import copy
import fcntl
import hashlib
import html
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from full_harness.codex import RESULT_SCHEMA, invoke
from full_harness.common import controls, digest, read_json, relative_file, write_json
from full_harness.runner import (
    api,
    event_input,
    framework_comment,
    new_state,
    recover_session,
)
from full_harness.timeline import publish

STAGES = ["requirements", "design", "development"]
SCHEMA = copy.deepcopy(RESULT_SCHEMA)
SCHEMA["properties"].update(
    {
        "stage": {"type": "string", "enum": STAGES},
        "awaiting_approval": {"type": "boolean"},
        "delivered": {"type": "boolean"},
        "approval_quote": {
            "type": "string",
            "description": "Exact quote from this user message confirming the pending documents; empty otherwise.",
        },
    }
)
SCHEMA["required"] = list(SCHEMA["properties"])


def hashes(workspace, names):
    result = {}
    for name in names:
        path = relative_file(workspace, name)
        if not path.is_file() or not path.stat().st_size:
            raise ValueError("产物不存在或为空：" + name)
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def validate_result(session, state, result, message, sent):
    """Check transport and approval evidence, never classify the user's words."""
    if set(result) != set(SCHEMA["required"]):
        raise ValueError("结果字段不完整")
    if result["stage"] not in STAGES or result["status"] not in {
        "ready",
        "needs_input",
        "blocked",
    }:
        raise ValueError("无效阶段或状态")
    for key in ("summary", "question", "approval_quote"):
        if not isinstance(result[key], str):
            raise ValueError("回复必须是文字")
    for key in ("awaiting_approval", "delivered"):
        if type(result[key]) is not bool:
            raise ValueError("无效结果标志")
    if not isinstance(result["artifacts"], list) or not all(
        isinstance(n, str) for n in result["artifacts"]
    ):
        raise ValueError("产物必须是路径列表")
    workspace = session / "workspace"
    if controls(workspace) != state["controls"]:
        raise ValueError("执行规则被修改，请恢复后继续")
    material = hashes(workspace, result["artifacts"])
    previous = STAGES.index(state["stage"])
    current = STAGES.index(result["stage"])
    if current > previous:
        pending = state.get("pending")
        quote = result["approval_quote"].strip()
        if current != previous + 1 or not pending or pending["stage"] != state["stage"]:
            raise ValueError("进入下一阶段需要先展示本阶段产物并获得确认")
        if not quote or quote not in message:
            raise ValueError("未找到本条消息对待审文档的确认原话")
        if hashes(workspace, pending["files"]) != pending["files"]:
            raise ValueError("待审文件发生变化，需要重新展示并确认")
        if sent and datetime.fromisoformat(
            sent.replace("Z", "+00:00")
        ) < datetime.fromisoformat(pending["requested_at"]):
            raise ValueError("这条消息早于待审文档，请查看当前版本后确认")
    if result["awaiting_approval"] and (
        not material or result["stage"] == "development" or result["status"] != "ready"
    ):
        raise ValueError("需求或设计产物就绪后才能请求确认")
    if result["delivered"] and (
        result["stage"] != "development"
        or result["status"] != "ready"
        or result["awaiting_approval"]
    ):
        raise ValueError("只有完成研发验证后才能交付")
    return material


def apply_result(session, state, result, message, sent):
    material = validate_result(session, state, result, message, sent)
    workspace = session / "workspace"
    if result["delivered"]:
        gate_path = session / "turns" / str(state["turn"]) / "gate.json"
        gate = read_json(gate_path) if gate_path.exists() else {}
        if gate.get("status") != "passed" or gate.get("snapshot") != digest(workspace):
            raise ValueError("研发校验尚未通过，不能交付")
    previous = STAGES.index(state["stage"])
    current = STAGES.index(result["stage"])
    if current > previous:
        state.setdefault("approvals", {})[state["stage"]] = {
            **state["pending"],
            "quote": result["approval_quote"],
            "turn": state["turn"],
        }
        state.pop("pending", None)
    elif current < previous:
        state.pop("pending", None)
        for stage in STAGES[current:]:
            state.get("approvals", {}).pop(stage, None)
    # Ordinary questions preserve an unchanged pending version. A document edit
    # invalidates it; the Agent can request confirmation of its new revision.
    pending = state.get("pending")
    if pending:
        try:
            unchanged = hashes(workspace, pending["files"]) == pending["files"]
        except ValueError:
            unchanged = False
        if not unchanged:
            state.pop("pending", None)
    if result["awaiting_approval"]:
        state["pending"] = {
            "stage": result["stage"],
            "files": material,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
    state.update(
        stage=result["stage"],
        status=result["status"],
        reply=result["summary"]
        + ("\n\n" + result["question"] if result["question"] else ""),
        artifacts=result["artifacts"],
        delivered=result["delivered"],
    )


def prompt(state, message):
    packet = {
        "task": state["task"],
        "stage": state["stage"],
        "message": message,
        "pending_confirmation": state.get("pending"),
        "confirmed": state.get("approvals", {}),
        "project_entries": state["config"]["entries"],
        "stages": {s: state["config"]["stages"][s] for s in STAGES},
        "checks": state["config"].get("checks", []),
    }
    return (
        "你直接与用户协作完成项目。本条消息只启动你这一次，不会另调意图分类或执行模型。"
        "首次读取 AGENTS.md 和项目入口，后续沿用当前原生 Session。按需读取原生 Skill；目录同时提供三个阶段的 Skill，优先当前阶段。"
        "理解用户是在提问、澄清、修改还是确认，然后直接回答或工作；不要只返回分类等另一个 Agent。"
        "需求、设计完成时，展示真实文档并用自然语言请用户确认，awaiting_approval=true。"
        "若本条消息明确确认 pending_confirmation 中的文档，在这同一次执行里进入下一阶段并使用该阶段 Skill，approval_quote 填确认原话。"
        "每次最多推进一个阶段，不能把需求确认当作设计确认。没有确认或只是提问就留在当前阶段。"
        "用户带来现有文档、原型或代码时，直接复用并简短列出待确认基线，不重新造文档；可以用一个简短文件索引现有材料。"
        "设计按任务需要覆盖 UI/原型和架构/数据契约，不强迫所有产品做网页。"
        "研发在本进程持续实现、格式化、lint、测试和修复；完成 Python 修改运行 python3 full_harness/quality.py fix，再 check。"
        "研发完毕生成配置指定的验证记录，并返回 delivered=true，原生 Stop Hook 会运行真实项目检查，失败会让你在同一次执行内继续修复。"
        "普通问答 delivered=false，不运行开发检查。缺用户决定时提问；环境卡住如实报告 blocked；不要为了等确认捏造澄清问题。"
        "不得修改执行规则、伪造验证、绕过产品入口、修改已确认文档后沿用旧批准。需要修改基线时回到对应阶段重新确认。"
        "审批事实留在结构化结果，不写进 PRD 正文。summary/question 是直接给用户看的原话，明确说做了什么及下一步需要什么。"
        "仅关键节点在 artifacts 列出实际文件相对路径；不要把内部 state、日志或凭证当产物。"
        "最终结果遵循 schema。当前为轻量模板，旧完整模板的只读意图调用、控制器审批登记和额外独立模型评审流程不适用。\n"
        + json.dumps(packet, ensure_ascii=False, indent=2)
    )


def execute(source, session, state, message, event_id, sent=None):
    if event_id in state.get("handled", []):
        return
    if state.get("active_event") == event_id:
        raise RuntimeError(
            "本条消息已有执行记录；请查看日志，发送新评论接续，避免重复执行"
        )
    state["turn"] += 1
    state["active_event"] = event_id
    write_json(session / "state.json", state)
    evidence = session / "turns" / str(state["turn"])
    context = {
        "state": copy.deepcopy(state),
        "message": message,
        "sent": sent,
        "source": str(source),
        "session": str(session),
        "workspace": str(session / "workspace"),
        "evidence": str(evidence),
        "config": state["config"],
        "controls": state["controls"],
        "task": state["task"],
        "stage": "development",
        "node_path": os.environ.get("NODE_PATH", ""),
        "deadline_monotonic": time.monotonic() + state["config"]["agent_timeout"],
    }
    context_path = evidence / "context.json"
    write_json(context_path, context)
    allowed = list(
        dict.fromkeys(n for s in STAGES for n in state["config"]["stages"][s]["skills"])
    )
    print("当前阶段：" + state["stage"] + " · 本条消息一次 Codex 执行", flush=True)
    result, sid = invoke(
        source,
        session / "workspace",
        session,
        prompt(state, message),
        evidence / "agent",
        session_id=recover_session(session),
        hook_context=context_path,
        hook_script="light_hook.py",
        schema_override=SCHEMA,
        skills=allowed,
    )
    apply_result(session, state, result, message, sent)
    state["session_id"] = sid
    state.setdefault("handled", []).append(event_id)
    state.pop("active_event", None)
    write_json(session / "state.json", state)


def report(session, state):
    public = Path(os.environ["LIGHT_PUBLIC"])
    public.mkdir(parents=True, exist_ok=True)
    body = state["reply"]
    for name in state.get("artifacts", []):
        path = relative_file(session / "workspace", name)
        if not path.is_file():
            continue
        target = relative_file(public, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        if (
            path.suffix.lower() in {".md", ".txt", ".json", ".yaml", ".yml"}
            and path.stat().st_size < 14000
        ):
            body += (
                "\n\n<details><summary>查看文档："
                + html.escape(name)
                + "</summary>\n\n<pre>"
                + html.escape(path.read_text())
                + "</pre>\n\n</details>"
            )
    url = f"https://github.com/{state['repo']}/actions/runs/{state['run_id']}"
    if state.get("pr_url"):
        body += "\n\n[交付 PR](" + state["pr_url"] + ")"
    body += "\n\n[运行日志及产物下载](" + url + ")"
    body = body.replace(str(session), "<private-runtime>").replace(
        str(Path.home()), "<private-runtime>"
    )
    if len(body) > 60000:
        body = (
            state["reply"][:12000]
            + "\n\n产物较长，请查看[运行日志及下载]("
            + url
            + ")。"
        )
    (public / "reply.md").write_text(body)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("当前阶段：" + state["stage"] + "\n\n" + body)
    publish(api, state, body)
    write_json(session / "state.json", state)


def main():
    source = Path(__file__).resolve().parents[1]
    event = read_json(os.environ["GITHUB_EVENT_PATH"])
    if framework_comment(event):
        return
    repo = os.environ["GITHUB_REPOSITORY"]
    number, message = event_input(
        event, repo, os.environ["GITHUB_ACTOR"], os.environ["GITHUB_EVENT_NAME"]
    )
    ref = os.environ["GITHUB_REF"]
    if not ref.startswith("refs/heads/"):
        raise ValueError("Only same-repository branches are supported")
    branch = ref[len("refs/heads/") :]
    root = Path(os.environ["FULL_STATE_ROOT"]).resolve()
    if not Path(os.environ["FULL_STATE_ROOT"]).is_absolute() or root.is_relative_to(
        source
    ):
        raise ValueError("Private state must be outside checkout")
    scope = hashlib.sha256((repo + "\0" + branch).encode()).hexdigest()[:16]
    session = root / "light" / scope / str(number)
    session.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (session / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state_path = session / "state.json"
        issue = api(repo, f"issues/{number}")
        if "pull_request" in issue or issue["state"] != "open":
            raise ValueError("Use an open Issue")
        task = {
            "number": number,
            "title": issue["title"],
            "body": issue.get("body") or "",
        }
        sha = os.environ["GITHUB_SHA"]
        runner = os.environ["RUNNER_NAME"]
        state = (
            read_json(state_path)
            if state_path.exists()
            else new_state(source, session, task, repo, sha, branch, runner)
        )
        if state["runner"] != runner or state["baseline"] != sha:
            raise ValueError("任务基线或执行机器变化，需先协调已有工作区")
        if state["stage"] == "entry":
            state["stage"] = "requirements"
        state["task"] = task
        state["run_id"] = os.environ["GITHUB_RUN_ID"]
        event_id = str(
            event.get("comment", {}).get("id")
            or (
                "issue-" + str(number)
                if os.environ["GITHUB_EVENT_NAME"] == "issues"
                else "run-" + state["run_id"]
            )
        )
        if state.get("pr_number"):
            pr = api(repo, "pulls/" + str(state["pr_number"]))
            if pr.get("merged_at") or pr.get("state") == "closed":
                raise ValueError("PR 已合入或关闭，请新建 Issue 开始下一次迭代")
        try:
            execute(
                source,
                session,
                state,
                message,
                event_id,
                event.get("comment", {}).get("created_at"),
            )
            if state.get("delivered"):
                from full_harness.light_delivery import deliver

                deliver(session, state)
        except Exception as error:
            state.update(
                status="blocked",
                delivered=False,
                artifacts=[],
                reply="这次执行遇到问题："
                + str(error)
                + "。现场和 Session 已保留，可查看日志后回复继续。",
            )
            write_json(state_path, state)
            report(session, state)
            raise
        report(session, state)


if __name__ == "__main__":
    main()
