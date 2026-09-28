#!/usr/bin/env python3
"""Stage Agents with separate native Sessions; no classifier or approval interpreter."""

import argparse
import copy
import fcntl
import hashlib
import html
import json
import os
import sys
import time
import uuid
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from full_harness.codex import invoke
from full_harness.common import controls, digest, read_json, relative_file, write_json
from full_harness.runner import (
    GitHubReadUnavailable,
    api,
    event_input,
    framework_comment,
    new_state,
    output,
    recover_session,
)
from full_harness.timeline import AgentReplies, progress_event, publish

STAGES = ["requirements", "design", "development"]
STATES = [*STAGES, "done"]
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "next_state": {"type": "string", "enum": STATES},
        "message": {"type": "string"},
        "artifacts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Existing project-relative files to show in THIS reply; [] for ordinary conversation.",
        },
    },
    "required": ["next_state", "message", "artifacts"],
}


def migrate(state):
    """Retain old task facts and Session while removing the old status flags."""
    pending = state.pop("pending", None)
    if pending:
        state.setdefault("documents", {})[pending["stage"]] = {
            "files": pending["files"],
            "shown_at": pending["requested_at"],
        }
    if state.pop("delivered", False) and state.get("pr_url"):
        state["stage"] = "done"
    for name in ("status", "reply_token", "reason"):
        state.pop(name, None)


def hashes(workspace, names):
    result = {}
    for name in names:
        path = relative_file(workspace, name)
        if not path.is_file() or not path.stat().st_size:
            raise ValueError("产物不存在或为空：" + name)
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def validate_result(session, state, result, message, sent):
    """Validate a proposed checkpoint, not the meaning of a conversation."""
    if not isinstance(result, dict) or set(result) != set(SCHEMA["required"]):
        raise ValueError("结果必须包含 next_state、message、artifacts 三个字段")
    if result["next_state"] not in STATES:
        raise ValueError("无效的接续位置")
    if not isinstance(result["message"], str) or not result["message"].strip():
        raise ValueError("回复不能为空")
    if not isinstance(result["artifacts"], list) or not all(
        isinstance(n, str) for n in result["artifacts"]
    ):
        raise ValueError("产物必须是路径列表")
    workspace = session / "workspace"
    if controls(workspace) != state["controls"]:
        raise ValueError("执行规则被修改，请恢复后继续")
    material = hashes(workspace, result["artifacts"])
    previous = STATES.index(state["stage"])
    current = STATES.index(result["next_state"])
    if current > previous + 1:
        raise ValueError("下一阶段必须由对应 Job 执行，不能跨过阶段")
    return material


def apply_result(session, state, result, message, sent):
    # Do not partially change the checkpoint when validation fails.
    updated = copy.deepcopy(state)
    migrate(updated)
    material = validate_result(session, updated, result, message, sent)
    previous = STATES.index(updated["stage"])
    current = STATES.index(result["next_state"])
    if result["next_state"] == "done":
        gate_path = session / "turns" / str(updated["turn"]) / "gate.json"
        gate = (
            read_json(gate_path)
            if gate_path.exists()
            else updated.get("verification", {})
        )
        if gate.get("status") != "passed" or gate.get("snapshot") != digest(
            session / "workspace"
        ):
            raise ValueError("研发校验尚未通过，不能记为完成交付")
        updated["verification"] = {
            **gate,
            "turn": updated["turn"] if gate_path.exists() else gate["turn"],
        }
    # Documents and handoffs are evidence, not a second approval state machine.
    stage = updated["stage"]
    documents = updated.setdefault("documents", {})
    if material:
        document = documents.setdefault(stage, {"files": {}})
        document["files"].update(material)
    next_state = result["next_state"]
    if current != previous:
        workspace = session / "workspace"
        files = hashes(
            workspace,
            [
                name
                for name in documents.get(stage, {}).get("files", {})
                if relative_file(workspace, name).is_file()
            ],
        )
        documents[stage] = {"files": files}
        updated.setdefault("history", []).append(
            {
                "from": stage,
                "to": next_state,
                "event_id": updated.get("active_event"),
                "message": message,
                "sent": sent,
                "reply": result["message"],
                "files": files,
            }
        )
    updated.update(
        stage=next_state, reply=result["message"], artifacts=result["artifacts"]
    )
    updated.pop("error", None)
    state.clear()
    state.update(updated)


def prompt(state, message):
    stage = "development" if state["stage"] == "done" else state["stage"]
    history = state.get("history", [])
    handoff = history[-1] if history and history[-1]["to"] == stage else None
    # The previous Agent consumed this event. Pass it as handoff context, not as
    # a fresh user instruction to the receiving Agent.
    arriving = (
        handoff
        and str(handoff.get("event_id") or "").rsplit(":", 1)[0]
        == state.get("active_event", "").rsplit(":", 1)[0]
    )
    packet = {
        "task": state["task"],
        "stage": stage,
        "message": "" if arriving else message,
        "handoff": handoff,
        "documents": {
            s: list(d["files"]) for s, d in state.get("documents", {}).items()
        },
        "project_entries": state["config"]["entries"],
        "stage_instructions": {
            key: value
            for key, value in state["config"]["stages"][stage].items()
            if key != "artifact" or stage == "development"
        },
        "checks": state["config"].get("checks", []),
    }
    return (
        "你是 stage 对应的阶段 Agent，按 AGENTS.md、项目索引和当前可用 Skill 工作。"
        "message 是用户本次新消息；handoff 是其他阶段 Agent 的交接记录，包含当时的用户消息和产物路径。"
        "本阶段恢复自己的 Session，跨阶段由另一 Agent 接手共享工作区和交接材料。"
        "过程消息使用 commentary；最终按 Schema 返回 next_state、message、artifacts。"
        "next_state 保持本阶段或交给相邻下一阶段，也可退回前面的阶段；done 仅用于研发完成。"
        "message 直接回复用户；artifacts 列出本次展示的实际相对文件路径，无需展示则为 []。\n"
        + json.dumps(packet, ensure_ascii=False, indent=2)
    )


def stage_session(session, stage):
    """Keep native thread mappings per stage; adopt a legacy thread only once."""
    agents = session / "agents"
    if not agents.exists():
        legacy = recover_session(session)
        if legacy:
            write_json(agents / stage / "codex-session.json", {"session_id": legacy})
        else:
            agents.mkdir()
    record = agents / stage / "codex-session.json"
    sid = read_json(record)["session_id"] if record.exists() else None
    # A hard cancellation can leave thread.started before invoke's finally runs.
    logs = sorted(
        (session / "turns").glob("*/agent/agent.jsonl"),
        key=lambda p: int(p.parents[1].name),
        reverse=True,
    )
    for log in logs:
        context = log.parent.parent / "context.json"
        if not context.exists() or read_json(context).get("stage_session") != stage:
            continue
        for line in log.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "thread.started":
                found = event["thread_id"]
                uuid.UUID(found)
                if sid and sid != found:
                    raise ValueError("阶段 Session 记录与执行日志不一致")
                write_json(record, {"session_id": found})
                return found, record
    return sid, record


def execute(source, session, state, message, event_id, sent=None):
    migrate(state)
    if event_id in state.get("handled", []):
        return
    if state.get("active_event") == event_id:
        raise RuntimeError(
            "本条消息已有执行记录；请查看日志，发送新评论接续，避免重复执行"
        )
    stage = "development" if state["stage"] == "done" else state["stage"]
    sid, session_record = stage_session(session, stage)
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
        "stage": stage,
        "stage_session": stage,
        "node_path": os.environ.get("NODE_PATH", ""),
        "deadline_monotonic": time.monotonic() + state["config"]["agent_timeout"],
    }
    context_path = evidence / "context.json"
    write_json(context_path, context)
    allowed = state["config"]["stages"][stage]["skills"]
    print("当前阶段：" + stage + " · 本阶段一次 Codex 执行", flush=True)
    replies = AgentReplies(
        api, state, evidence / "issue-progress.json", (session, Path.home())
    )
    try:
        result, sid = invoke(
            source,
            session / "workspace",
            session,
            prompt(state, message),
            evidence / "agent",
            session_id=sid,
            session_record=session_record,
            hook_context=context_path if stage == "development" else None,
            hook_script="light_hook.py",
            schema_override=SCHEMA,
            skills=allowed,
            timeout_override=state["config"]["agent_timeout"],
            on_event=replies,
        )
    except BaseException:
        replies.finish(False)
        raise
    replies.finish(True)
    apply_result(session, state, result, message, sent)
    state["session_id"] = sid
    state.setdefault("handled", []).append(event_id)
    state.pop("active_event", None)
    write_json(session / "state.json", state)


def report(session, state, error=None, continuous=False):
    public = Path(os.environ["LIGHT_PUBLIC"])
    if continuous:
        public = public / "turns" / str(state["turn"])
    public.mkdir(parents=True, exist_ok=True)
    body = error or state["reply"]
    evidence = session / "turns" / str(state["turn"])
    context_path = evidence / "context.json"
    before = (
        read_json(context_path)["state"]["stage"]
        if context_path.exists()
        else state["stage"]
    )
    body += "\n\n本轮执行：" + ("执行失败" if error else "已结束")
    body += f"\n\n本轮阶段（开始 → 已保存）：`{before} → {state['stage']}`"
    if (
        continuous
        and not error
        and state["stage"] == before
        and state["stage"] != "done"
    ):
        body += "\n\n当前 Workflow 仍在运行，正在等你的下一条回复；直接在本 Issue 评论即可，无需重新启动。"
    # Read the actual current-turn output, including a proposal rejected by checks.
    # Never reconstruct it from the checkpoint or fall back to an earlier turn.
    rendered = None
    try:
        raw = read_json(evidence / "agent/result.json")
        if not isinstance(raw, dict):
            raise ValueError("Agent result is not an object")
        rendered = json.dumps(raw, ensure_ascii=False, indent=2)
        rendered = rendered.replace(str(session), "<private-runtime>").replace(
            str(Path.home()), "<private-runtime>"
        )
        (public / "agent-result.json").write_text(rendered + "\n")
    except (OSError, ValueError):
        (public / "agent-result.json").unlink(missing_ok=True)
        body += "\n\n本轮未取得可解析的 Agent 结构化输出。"
    events = []
    log = evidence / "agent/agent.jsonl"
    if log.exists():
        for line in log.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if progress_event(event):
                events.append(event)
    if events:
        rendered = json.dumps(events, ensure_ascii=False, indent=2)
        rendered = rendered.replace(str(session), "<private-runtime>").replace(
            str(Path.home()), "<private-runtime>"
        )
        (public / "agent-events.json").write_text(rendered + "\n")
    else:
        (public / "agent-events.json").unlink(missing_ok=True)
    if rendered is not None:
        label = (
            "Codex 原始消息与状态事件（完整 JSON）"
            if events
            else "最终结果 JSON（本轮无原始事件日志）"
        )
        body += "\n\n<details><summary>" + label + "</summary>\n\n"
        if len(html.escape(rendered)) < 24000:
            body += "<pre>" + html.escape(rendered) + "</pre>"
        else:
            body += "完整 JSON 较长，请从本轮产物下载 agent-events.json 和 agent-result.json（如有）。"
        body += "\n\nitem.completed 只表示一个消息或工具项结束；turn.completed 表示 Codex 本轮输出结束，任务是否完成以保存阶段为准。\n\n</details>"
    for name in [] if error else state.get("artifacts", []):
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
    if continuous:
        body += "（文档可在本条评论展开；下载包在本阶段 Job 结束后提供。）"
    body = body.replace(str(session), "<private-runtime>").replace(
        str(Path.home()), "<private-runtime>"
    )
    if len(body) > 60000:
        body = body[:12000] + "\n\n产物较长，请查看[运行日志及下载](" + url + ")。"
    (public / "reply.md").write_text(body)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("当前阶段：" + state["stage"] + "\n\n" + body)
    publish(api, state, body)
    write_json(session / "state.json", state)


def wait_for_reply(session, state, deadline, poll_seconds):
    """Read the Issue inbox in order; persist the cursor only after validation."""
    print(
        "等待 Issue 回复；当前 Job 保持运行，收到有权限用户的消息后接续。", flush=True
    )
    repo = state["repo"]
    number = state["task"]["number"]
    failures = 0
    while time.monotonic() < deadline:
        try:
            issue = api(repo, f"issues/{number}")
            if issue["state"] != "open":
                print("Issue 已关闭，停止等待。", flush=True)
                return None
            page = 1
            while True:
                comments = api(
                    repo, f"issues/{number}/comments?per_page=100&page={page}"
                )
                for comment in comments:
                    comment_id = int(comment["id"])
                    if comment_id <= state.get("comment_cursor", 0):
                        continue
                    user = comment.get("user", {})
                    actor = user.get("login", "")
                    body = (comment.get("body") or "").strip()
                    permitted = False
                    if (
                        user.get("type") == "User"
                        and actor
                        and body
                        and not framework_comment({"comment": comment})
                        and not any(
                            event == str(comment_id)
                            or event.startswith(str(comment_id) + ":")
                            for event in state.get("handled", [])
                        )
                    ):
                        # A deleted/non-collaborating user has no write permission.
                        # API/network errors fail closed without consuming their message.
                        if actor.casefold() == repo.split("/")[0].casefold():
                            permitted = True
                        else:
                            permission = api(
                                repo, "collaborators/" + actor + "/permission"
                            )
                            permitted = permission.get("permission") in {
                                "write",
                                "maintain",
                                "admin",
                            }
                    state["comment_cursor"] = comment_id
                    if permitted:
                        state["conversation_input"] = {
                            "id": str(comment_id),
                            "message": body,
                            "sent": comment["created_at"],
                        }
                        state["start_stage"] = state["stage"]
                    write_json(session / "state.json", state)
                    if permitted:
                        print(
                            f"收到评论 {comment_id}，恢复 {state['stage']} Session。",
                            flush=True,
                        )
                        return state["conversation_input"]
                if len(comments) < 100:
                    break
                page += 1
        except GitHubReadUnavailable as error:
            failures += 1
            delay = min(60, 5 * 2 ** min(failures - 1, 4))
            print(
                f"GitHub 暂时不可达，{delay} 秒后重试读取；Session 与未读评论保留。{error}",
                flush=True,
            )
            time.sleep(min(delay, max(0, deadline - time.monotonic())))
            continue
        if failures:
            print("GitHub 连接已恢复，继续等待评论。", flush=True)
            failures = 0
        time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
    raise TimeoutError(
        "本次等待时间已用完，Session 和阶段已保存。请到 Actions 手动运行本工作流，"
        "填写同一 Issue 编号接续；仅发评论不会重新启动已结束的运行。"
    )


def run_stage(source, session, state, job, first_input, deadline=None, poll_seconds=15):
    """Keep one stage Job alive across user turns; model owns stage decisions."""
    incoming = first_input
    while True:
        event_id = incoming["id"] + ":" + job
        execute(
            source, session, state, incoming["message"], event_id, incoming.get("sent")
        )
        if state["stage"] == "done":
            from full_harness.light_delivery import deliver

            deliver(session, state)
        report(session, state, continuous=deadline is not None)
        if deadline is None:
            return
        if state["stage"] != job:
            if state["stage"] in STAGES and STAGES.index(state["stage"]) < STAGES.index(
                job
            ):
                publish(
                    api,
                    state,
                    "已保存退回阶段。当前流水线不能倒序重开已结束的 Job；请在 Actions 手动运行同一 Issue 接续。",
                )
                write_json(session / "state.json", state)
            return
        incoming = wait_for_reply(session, state, deadline, poll_seconds)
        if incoming is None:
            return


def main(job="restore", wait_seconds=None, poll_seconds=15):
    if job not in ["restore", *STAGES]:
        raise ValueError("Unknown stage job")
    deadline = time.monotonic() + wait_seconds if wait_seconds is not None else None
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
        migrate(state)
        if state["runner"] != runner or state["baseline"] != sha:
            raise ValueError("任务基线或执行机器变化，需先协调已有工作区")
        if state["stage"] == "entry":
            state["stage"] = "requirements"
        state["task"] = task
        run_id = os.environ["GITHUB_RUN_ID"]
        event_id = str(
            event.get("comment", {}).get("id")
            or (
                "issue-" + str(number)
                if os.environ["GITHUB_EVENT_NAME"] == "issues"
                else "run-" + run_id
            )
        )
        if job == "restore":
            new_run = state.get("run_id") != run_id or "conversation_input" not in state
            previous_start = state.get("start_stage", state["stage"])
            # Old single-job events stay consumed. Do not silently rerun history.
            if event_id in state.get("handled", []):
                output("stage", "")
                return ""
            if state.get("event_id") != event_id:
                if any(x.startswith(event_id + ":") for x in state.get("handled", [])):
                    output("stage", "")
                    return ""
                state.update(
                    event_id=event_id,
                    run_id=run_id,
                    start_stage="development"
                    if state["stage"] == "done"
                    else state["stage"],
                )
            elif state["run_id"] != run_id:
                output("stage", "")
                return ""
            if wait_seconds is not None and new_run:
                previous_input = state.get("conversation_input")
                previous_key = (
                    (previous_input["id"] + ":" + state["stage"])
                    if previous_input
                    else None
                )
                if (
                    previous_input
                    and previous_key not in state.get("handled", [])
                    and previous_key != state.get("active_event")
                ):
                    state["start_stage"] = previous_start
                    # The cursor may have been saved just before cancellation.
                    # Keep accepted input which never reached execute().
                    if message:
                        previous_input["message"] += "\n\n手动接续补充：" + message
                else:
                    state["conversation_input"] = {
                        "id": event_id,
                        "message": message,
                        "sent": event.get("comment", {}).get("created_at"),
                    }
            write_json(state_path, state)
            restored_stage = (
                (state["stage"] if state["stage"] != "done" else "development")
                if wait_seconds is not None
                else state["start_stage"]
            )
            output("stage", restored_stage)
            print("恢复阶段：" + state["stage"] + "（不调用模型）", flush=True)
            return restored_stage
        if state.get("event_id") != event_id or state.get("run_id") != run_id:
            raise ValueError("请先在本轮 restore Job 恢复任务，再执行对应阶段")
        incoming = (
            state["conversation_input"]
            if wait_seconds is not None
            else {
                "id": event_id,
                "message": message,
                "sent": event.get("comment", {}).get("created_at"),
            }
        )
        stage_event = incoming["id"] + ":" + job
        handled = state.get("handled", [])
        if (
            stage_event not in handled
            and state["stage"] != job
            and not (job == "development" and state["stage"] == "done")
        ):
            raise ValueError("任务当前阶段与 Job 不匹配")
        if stage_event in handled and (
            stage_event != handled[-1] or state.get("active_event")
        ):
            next_stage = next(
                (
                    h["to"]
                    for h in reversed(state["history"])
                    if h.get("event_id") == stage_event
                    and h["to"] in STAGES
                    and STAGES.index(h["to"]) > STAGES.index(job)
                ),
                "",
            )
            output("next_stage", next_stage)
            return next_stage
        if state.get("pr_number"):
            pr = api(repo, "pulls/" + str(state["pr_number"]))
            if pr.get("merged_at") or pr.get("state") == "closed":
                raise ValueError("PR 已合入或关闭，请新建 Issue 开始下一次迭代")
        try:
            run_stage(source, session, state, job, incoming, deadline, poll_seconds)
        except Exception as error:
            state["error"] = str(error)
            write_json(state_path, state)
            notice = (
                "这次执行遇到问题："
                + str(error)
                + "。现场和 Session 已保留。"
                + (
                    "请在 Actions 手动运行同一 Issue 接续。"
                    if wait_seconds is not None
                    else "可查看日志后回复继续。"
                )
            )
            if wait_seconds is not None and not state.get("active_event"):
                # Waiting/transport failure is not failure of the last model turn.
                publish(api, state, notice)
                write_json(state_path, state)
            else:
                report(session, state, notice, continuous=wait_seconds is not None)
            raise
        state.pop("error", None)
        next_stage = (
            state["stage"]
            if state["stage"] in STAGES
            and STAGES.index(state["stage"]) > STAGES.index(job)
            else ""
        )
        output("next_stage", next_stage)
        return next_stage


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", choices=["restore", *STAGES])
    parser.add_argument(
        "--wait-seconds",
        type=int,
        help="Keep this stage Job alive for Issue replies, including execution time",
    )
    args = parser.parse_args()
    if args.wait_seconds is not None and args.wait_seconds <= 0:
        parser.error("--wait-seconds must be positive")
    main(args.job, wait_seconds=args.wait_seconds)
