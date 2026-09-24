#!/usr/bin/env python3
"""Independent staged workflow. Task state and native sessions remain on one Runner."""

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from full_harness.codex import invoke
from full_harness.common import (
    STAGES,
    clean_env,
    configuration,
    controls,
    digest,
    files,
    read_json,
    relative_file,
    run_process,
    write_json,
)
from full_harness.dialogue import respond
from full_harness.quality import checks as quality_checks
from full_harness.router import classify
from full_harness.stop_hook import review_prompt


def api(repo, path, method="GET", data=None):
    argv = ["gh", "api", "repos/" + repo + "/" + path, "--method", method]
    if data is not None:
        argv += ["--input", "-"]
    result = subprocess.run(
        argv,
        input=json.dumps(data) if data is not None else None,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode:
        raise RuntimeError("GitHub API failed: " + path + " " + result.stderr[-800:])
    return json.loads(result.stdout) if result.stdout.strip() else None


def output(name, value):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(name + "=" + str(value) + "\n")


def authorized(repo, actor):
    if not actor or actor.endswith("[bot]"):
        return False
    if actor.casefold() == repo.split("/")[0].casefold():
        return True
    permission = api(repo, "collaborators/" + actor + "/permission")
    return permission.get("permission") in {"admin", "maintain", "write"}


def event_input(event, repo, actor, event_name):
    if event.get("sender", {}).get("type") == "Bot":
        raise ValueError("Bot events cannot start the Runner")
    if not authorized(repo, actor) or not authorized(
        repo, os.environ.get("GITHUB_TRIGGERING_ACTOR", actor)
    ):
        raise ValueError("Repository write, maintain or admin permission is required")
    if "pull_request" in event.get("issue", {}):
        raise ValueError("Use an Issue, not a pull request comment")
    if event_name == "workflow_dispatch":
        inputs = event.get("inputs", {})
        task = inputs.get("task", "")
        instruction = inputs.get("instruction", "")
    elif event_name == "issues" and event.get("action") == "opened":
        task = event["issue"]["number"]
        instruction = ""
    elif event_name == "issue_comment" and event.get("action") == "created":
        if event.get("comment", {}).get("user", {}).get("type") == "Bot":
            raise ValueError("Bot comments cannot start the Runner")
        instruction = event["comment"]["body"].strip()
        if re.match(r"^/develop(?:\s|$)", instruction):
            instruction = instruction[len("/develop") :].strip()
        task = event["issue"]["number"]
    else:
        raise ValueError("Unsupported entry event")
    if not str(task).isdigit() or int(task) < 1:
        raise ValueError("Task must be an existing Issue number")
    return int(task), instruction


def new_state(source, session, task, repo, sha, branch, runner):
    cfg = configuration(source)
    if (source / ".codex").exists():
        raise ValueError(
            "Unreviewed project .codex config is not supported by this runtime"
        )
    workspace = session / "workspace"
    if workspace.exists():
        raise ValueError("Partial initialization retained; inspect before restarting")
    workspace.mkdir()
    for name, data in files(source).items():
        dest = relative_file(workspace, name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        dest.chmod((source / name).stat().st_mode & 0o777)
    git_env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "GH_"))}
    for argv in [
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=Harness",
            "-c",
            "user.email=harness@example.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "Task baseline",
        ],
    ]:
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", *argv],
            cwd=workspace,
            env=git_env,
            check=True,
            capture_output=True,
        )
    state = {
        "version": 1,
        "repo": repo,
        "task": task,
        "baseline": sha,
        "branch": branch,
        "runner": runner,
        "stage": "entry",
        "status": "running",
        "completed": {},
        "turn": 0,
        "config": cfg,
        "controls": controls(workspace),
        "baseline_files": {
            n: hashlib.sha256(b).hexdigest() for n, b in files(workspace).items()
        },
        "baseline_modes": {
            n: ((workspace / n).stat().st_mode & 0o111) for n in files(workspace)
        },
        "history": [],
    }
    return state


def begin(state, instruction, sha, runner, run_id, session=None):
    if state["runner"] != runner:
        raise ValueError("Persistent state belongs to another Runner")
    if state["baseline"] != sha:
        raise ValueError(
            "Base revision changed: reconcile in a new task before continuing; previous evidence cannot be reused silently"
        )
    if state["status"] == "delivered":
        raise ValueError(
            "This task has delivered; start a new Issue for the next iteration"
        )
    if state["status"] in {
        "needs_input",
        "blocked",
        "waiting_review",
        "awaiting_approval",
    }:
        token = state["reply_token"]
        if not instruction.startswith(token + " "):
            raise ValueError(
                "Reply with /develop "
                + token
                + " followed by your answer or recovery instruction"
            )
        instruction = instruction[len(token) :].strip()
    if state["status"] == "awaiting_approval":
        stage = state["stage"]
        if instruction == "approve":
            if session is None:
                raise ValueError("Approval requires retained task files")
            pending = state["pending_approval"]
            if material_hashes(session, state, stage) != pending["files"]:
                raise ValueError(
                    "Documents changed after the confirmation request; review the new revision first"
                )
            state.setdefault("approvals", {})[stage] = {**pending, "run_id": run_id}
            state["stage"] = next_stage(state, stage)
            instruction = "用户已明确确认 " + stage + " 阶段产物。继续下一阶段。"
        else:
            invalidate(state, stage)
            state["feedback"] = "用户对阶段产物的修改意见：" + instruction
        state.pop("pending_approval", None)
    if state["status"] == "waiting_review":
        invalidate(state, "development")
    state.update(instruction=instruction, status="running", run_id=run_id)
    state.pop("reply_token", None)
    state.pop("reason", None)


def handle_message(source, session, state, instruction, event, sha, runner, run_id):
    """Return True only when this message authorizes continued stage execution."""
    if state["runner"] != runner or state["baseline"] != sha:
        raise ValueError("Task runtime/baseline changed; reconcile before continuing")
    token = state.get("reply_token", "")
    if token and instruction.startswith(token + " "):
        instruction = instruction[len(token) :].strip()
    # Empty legacy /develop can start a new task, but cannot approve a waiting one.
    if not instruction:
        state["run_id"] = run_id
        return state["status"] == "running"
    state["turn"] += 1
    evidence = session / "turns" / str(state["turn"]) / "agent"
    before = digest(session / "workspace")
    result = respond(
        source, session, state, instruction, evidence, recover_session(session)
    )
    if digest(session / "workspace") != before:
        raise ValueError("Read-only conversation changed project files")
    state["run_id"] = run_id
    state["last_reply"] = result["summary"] + (
        "\n" + result["question"] if result["question"] else ""
    )
    state.setdefault("conversation", []).append(
        {
            "message": instruction,
            "reply": state["last_reply"],
            "intent": result["intent"],
        }
    )
    intent = result["intent"]
    if intent == "answer":
        return False
    if intent == "pause":
        pause(state, "paused", "已按你的要求暂停。直接评论即可继续讨论或恢复。")
        return False
    if intent == "approve":
        if state["status"] != "awaiting_approval":
            state["last_reply"] += "\n当前没有待批准的阶段产物；未推进阶段。"
            return False
        quote = result["approval_quote"].strip()
        if not quote or quote not in instruction:
            state["last_reply"] += (
                "\n未找到明确的确认原话，请说明是否认可当前待审版本。"
            )
            return False
        requested = state["pending_approval"].get("requested_at")
        sent = event.get("comment", {}).get("created_at")
        if not requested or (
            sent
            and datetime.fromisoformat(sent.replace("Z", "+00:00"))
            < datetime.fromisoformat(requested)
        ):
            state["last_reply"] += (
                "\n这条评论早于当前待审版本，或旧状态缺少版本时间。请重新查看后确认。"
            )
            if not requested:
                state["pending_approval"]["requested_at"] = (
                    datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                )
            return False
        instruction = "approve"
    elif intent == "continue" and state["status"] == "awaiting_approval":
        state["last_reply"] += "\n当前需要确认产物；尚未明确批准，因此保留待审状态。"
        return False
    elif intent == "change":
        state["feedback"] = "用户修改意见：" + instruction
    # Existing version checks remain internal; users no longer copy a token.
    bound = (
        (state.get("reply_token", "") + " " + instruction).strip()
        if state["status"]
        in {"needs_input", "blocked", "waiting_review", "awaiting_approval"}
        else instruction
    )
    begin(state, bound, sha, runner, run_id, session)
    return True


def pause(state, status, reason):
    state.update(status=status, reason=reason, reply_token=uuid.uuid4().hex[:10])


def agent_input(state, stage, session):
    """First call gets task context; resume gets changed facts and current stage only."""
    cfg = state["config"]
    spec = cfg["stages"][stage]
    packet = {
        "task": state["task"],
        "stage": stage,
        "instruction": state.get("instruction", ""),
        "project_entries": cfg["entries"],
        "completed": state["completed"],
        "routing": state.get("routing"),
        "stage_instruction": spec.get(
            "instruction", "完成当前阶段并留下可检查的交接产物。"
        ),
        "inputs": [
            x.replace("{task}", str(state["task"]["number"]))
            for x in spec.get("inputs", [])
        ],
        "allowed_skills": spec["skills"],
        "handoff_artifact": spec["artifact"].replace(
            "{task}", str(state["task"]["number"])
        ),
        "checks": cfg.get("checks", []),
        "feedback": state.get("feedback", ""),
    }
    if stage == "development":
        packet["python_quality"] = (
            "Python 代码完成后运行 python3 full_harness/quality.py fix，再运行 python3 full_harness/quality.py check。修复剩余 lint 错误；不得降低规则。Stop Hook 和后续验证会独立检查，不能代替功能测试。"
        )
    previous = None
    # Only suppress prior input after a completed native turn. An interrupted/preflight-only call may not have delivered it.
    for path in sorted(
        (session / "turns").glob("*/agent/input.json"),
        key=lambda p: int(p.parents[1].name),
        reverse=True,
    ):
        log = path.parent / "agent.jsonl"
        if not log.exists():
            continue
        for line in log.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "turn.completed":
                previous = read_json(path)
                break
        if previous is not None:
            break
    if previous is None:
        message = (
            "先阅读项目入口和实际材料。按本阶段目标执行；可复用已有产物，低风险任务保持简短。"
            "Skill 由 Codex 原生目录提供，按适用范围选择本阶段 Skills，需要时再读取正文与引用，不必全部加载。"
            "缺少用户产品或架构决定时返回 needs_input；环境无法推进返回 blocked；完成本阶段返回 ready，由检查决定是否通过。"
            "不得伪造验证、绕过产品入口或修改受保护执行规则。把公共决定写入项目文档。\n"
        )
        content = packet
    else:
        content = {k: v for k, v in packet.items() if previous.get(k) != v}
        content["stage"] = stage
        # Repeat a response even when identical to the previous answer; it is a new user event.
        content["instruction"] = packet["instruction"]
        message = (
            "继续当前原生会话。以下是本轮新增或变化的信息；其余沿用此前上下文。"
            "仅在本轮原生 Skill 目录允许范围内选择适用 Skill，旧阶段 Skill 不再作为本阶段指令。\n"
        )
    return message + json.dumps(content, ensure_ascii=False, indent=2), packet


def checkpoint(session, state):
    write_json(session / "state.json", state)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        report(session, state)
        write_json(session / "state.json", state)


def recover_session(session):
    """Recover a thread.started checkpoint if cancellation killed the controller."""
    saved = session / "codex-session.json"
    sid = read_json(saved)["session_id"] if saved.exists() else None
    logs = sorted(
        (session / "turns").glob("*/agent/agent.jsonl"),
        key=lambda p: int(p.parents[1].name),
    )
    for log in reversed(logs):
        for line in log.read_text().splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if item.get("type") == "thread.started":
                found = item["thread_id"]
                uuid.UUID(found)
                if sid and sid != found:
                    raise ValueError(
                        "Native session checkpoint conflicts with execution history"
                    )
                write_json(saved, {"session_id": found})
                return found
    if sid:
        return sid
    if any((session / "codex-home/sessions").rglob("*.jsonl")):
        raise ValueError(
            "Native sessions exist without a verified task mapping; inspect retained state"
        )
    return None


def next_stage(state, after=None):
    start = STAGES.index(after) + 1 if after else 0
    for stage in STAGES[start:]:
        if stage not in state["completed"] or (
            stage in STAGES[:2] and stage not in state.get("approvals", {})
        ):
            return stage
    return "delivery"


def invalidate(state, stage):
    for name in STAGES[STAGES.index(stage) :]:
        state["completed"].pop(name, None)
        state.get("approvals", {}).pop(name, None)
    state["stage"] = stage


def material_hashes(session, state, stage):
    done = state["completed"][stage]
    names = set(done.get("artifacts", [])) | set(done.get("evidence", {}))
    if done.get("artifact"):
        names.add(done["artifact"])
    result = {}
    for name in sorted(names):
        if name == "issue":
            data = json.dumps(
                state["task"], ensure_ascii=False, sort_keys=True
            ).encode()
        else:
            data = relative_file(session / "workspace", name).read_bytes()
        result[name] = hashlib.sha256(data).hexdigest()
    # A no-design decision is also a versioned decision the Owner must see and confirm.
    result["@decision"] = hashlib.sha256(
        json.dumps(done, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return result


def request_approval(session, state, stage):
    state["stage"] = stage
    state["pending_approval"] = {
        "stage": stage,
        "files": material_hashes(session, state, stage),
        "requested_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    pause(
        state,
        "awaiting_approval",
        "请审查本阶段产物。确认后才进入下一阶段；回复修改意见则继续当前阶段。",
    )


def changed_approval(session, state):
    for stage in STAGES[:2]:
        approved = state.get("approvals", {}).get(stage)
        if approved:
            try:
                current = material_hashes(session, state, stage)
            except (OSError, KeyError):
                return stage
            if current != approved["files"]:
                return stage
    return None


def development(source, session, state):
    """One visible development Job owns implementation, checks, review and delivery."""
    for name in STAGES[:2]:
        if name not in state.get("approvals", {}):
            raise ValueError("Missing human confirmation: " + name)
    while state["status"] == "running":
        changed = changed_approval(session, state)
        if changed:
            invalidate(state, changed)
            state["feedback"] = "已确认产物变化，重新检查并请求人工确认。"
        stage = state["stage"]
        if stage in STAGES[:3]:
            run_agent(source, session, state, stage)
        elif stage == "verification":
            verify_stage(source, session, state)
        elif stage == "review":
            review_stage(source, session, state)
        elif stage == "delivery":
            deliver(session, state)
        else:
            raise ValueError("Unknown development step: " + stage)


def assess_entry(source, session, state):
    state["turn"] += 1
    checkpoint(session, state)
    result = classify(
        source,
        session / "workspace",
        session,
        state,
        session / "turns" / str(state["turn"]) / "routing",
    )
    state["routing"] = result
    if result["status"] != "ready":
        pause(state, result["status"], result["question"] or result["summary"])
        return
    # Assessment can invalidate earlier outcomes when feedback changes the task.
    state["completed"] = {}
    for item in result["decisions"]:
        if item["action"] != "run":
            state["completed"][item["stage"]] = {
                "mode": item["action"],
                "summary": item["reason"],
                "evidence": item["evidence_hashes"],
            }
    state["stage"] = next_stage(state)


def verify_stage(source, session, state, attempt=0):
    if attempt >= state["config"]["max_attempts"]:
        pause(state, "blocked", "Verification repair limit reached")
        return
    workspace = session / "workspace"
    checks = [
        c
        for c in state["config"].get("checks", [])
        if set(c.get("stages", ["development"])) & {"development", "verification"}
    ]
    if not checks:
        raise ValueError(
            "No Owner-configured verification checks; routing cannot bypass verification"
        )
    checks += quality_checks(workspace)
    if controls(workspace) != state["controls"]:
        raise ValueError("Execution controls changed")
    before = digest(workspace)
    impl = state["completed"].get("development", {})
    # Reuse an exact matching, controller-produced gate; never a model claim.
    gate_path = session / "turns" / str(impl.get("turn", "missing")) / "gate.json"
    gate = read_json(gate_path) if gate_path.exists() else {}
    only_implementation = all(
        "development" in c.get("stages", ["development"]) for c in checks
    )
    if (
        only_implementation
        and gate.get("status") == "passed"
        and gate.get("snapshot") == before
    ):
        outcomes = gate["checks"]
    else:
        state["turn"] += 1
        checkpoint(session, state)
        evidence = session / "turns" / str(state["turn"])
        evidence.mkdir(parents=True)
        outcomes = []
        for i, check in enumerate(checks):
            log = evidence / f"check-{i}.log"
            env = clean_env()
            if os.environ.get("NODE_PATH"):
                env["NODE_PATH"] = os.environ["NODE_PATH"]
            argv = [
                x.replace("{workspace}", str(workspace)).replace(
                    "{evidence}", str(evidence)
                )
                for x in check["argv"]
            ]
            code = run_process(
                argv,
                relative_file(workspace, check.get("cwd", ".")),
                env,
                log,
                state["config"]["check_timeout"],
            )
            outcomes.append({"name": check["name"], "code": code, "log": log.name})
            if code in (124, 125):
                raise ValueError(
                    "Verification environment unavailable: " + check["name"]
                )
            if code:
                state["feedback"] = (
                    check["name"] + " failed: " + log.read_text()[-6000:]
                )
                state["completed"].pop("development", None)
                # Real check failure goes into the existing bounded implementation
                # loop, not back to the human just because code was supplied.
                run_agent(source, session, state, "development")
                if state["status"] != "running":
                    return
                # A verification-only failing check must also be included in the
                # implementation gate, so repaired code is checked before return.
                return verify_stage(source, session, state, attempt + 1)
        if digest(workspace) != before:
            raise ValueError("Verification changed project files; evidence invalidated")
    state["completed"]["verification"] = {
        "summary": "Owner-configured checks passed",
        "checks": outcomes,
        "snapshot": digest(workspace),
    }
    state["stage"] = "review"


def run_agent(source, session, state, stage):
    if (
        stage in STAGES[:2]
        and stage in state["completed"]
        and stage not in state.get("approvals", {})
    ):
        request_approval(session, state, stage)
        return
    workspace = session / "workspace"
    state["turn"] += 1
    state["stage"] = stage
    checkpoint(session, state)
    print("Executing stage: " + stage, flush=True)
    evidence = session / "turns" / str(state["turn"])
    evidence.mkdir(parents=True)
    context = {
        "source": str(source),
        "workspace": str(workspace),
        "session": str(session),
        "evidence": str(evidence),
        "task": state["task"],
        "instruction": state.get("instruction", ""),
        "routing": state.get("routing"),
        "stage": stage,
        "config": state["config"],
        "controls": state["controls"],
        "baseline": state["baseline"],
        "approved_files": {
            n: h
            for approval in state.get("approvals", {}).values()
            for n, h in approval["files"].items()
            if n not in {"issue", "@decision"}
        },
        "deadline_monotonic": time.monotonic() + state["config"]["agent_timeout"],
        "node_path": os.environ.get("NODE_PATH", ""),
    }
    write_json(evidence / "context.json", context)
    sid = recover_session(session)
    prompt, packet = agent_input(state, stage, session)
    try:
        result, sid = invoke(
            source,
            workspace,
            session,
            prompt,
            evidence / "agent",
            sid,
            evidence / "context.json",
            skills=state["config"]["stages"][stage]["skills"],
        )
    finally:
        # Preserve the compact input checkpoint even if a started native turn is interrupted.
        if (evidence / "agent").exists():
            write_json(evidence / "agent/input.json", packet)
    gate = (
        read_json(evidence / "gate.json")
        if (evidence / "gate.json").exists()
        else {
            "status": "blocked",
            "reason": "Native Stop Hook did not supply a verified gate",
        }
    )
    state["history"].append(
        {
            "stage": stage,
            "turn": state["turn"],
            "session_id": sid,
            "agent": result["status"],
            "gate": gate["status"],
        }
    )
    changed = changed_approval(session, state)
    if changed:
        invalidate(state, changed)
        state["feedback"] = (
            "已确认的 " + changed + " 产物发生变化；重新检查并提交人工确认。"
        )
        run_agent(source, session, state, changed)
        return
    if result["status"] != "ready":
        pause(state, result["status"], result["question"] or result["summary"])
        return
    if gate["status"] != "passed":
        pause(
            state,
            gate["status"]
            if gate["status"] in {"needs_input", "blocked"}
            else "blocked",
            gate.get("reason", "Gate did not pass"),
        )
        return
    if (
        gate.get("snapshot") != digest(workspace)
        or controls(workspace) != state["controls"]
    ):
        pause(state, "blocked", "Workspace changed after verification")
        return
    artifact = gate["artifact"]
    path = relative_file(workspace, artifact)
    state["completed"][stage] = {
        "artifact": artifact,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "summary": result["summary"],
        "checks": gate.get("checks", []),
        "turn": state["turn"],
        "artifacts": sorted(set([artifact] + result.get("artifacts", []))),
    }
    state["feedback"] = ""
    if stage in STAGES[:2]:
        request_approval(session, state, stage)
    else:
        state["stage"] = next_stage(state, stage)


def review_stage(source, session, state):
    workspace = session / "workspace"
    # The independent review may invalidate an earlier stage. Repairs are bounded
    # and use the original builder session, never the reviewer session.
    if state["completed"].get("verification", {}).get("snapshot") != digest(workspace):
        verify_stage(source, session, state)
        if state["status"] != "running":
            return
    for attempt in range(state["config"]["max_attempts"]):
        state["turn"] += 1
        state["stage"] = "review"
        checkpoint(session, state)
        print("Executing independent review", flush=True)
        evidence = session / "turns" / str(state["turn"])
        context = {
            "task": state["task"],
            "config": state["config"],
            "baseline": state["baseline"],
            "instruction": state.get("instruction", ""),
            "routing": state.get("routing"),
            "check_results": state["completed"]
            .get("verification", {})
            .get("checks", []),
        }
        before = digest(workspace)
        result, sid = invoke(
            source,
            workspace,
            session,
            review_prompt(source, workspace, context, "review"),
            evidence,
            review=True,
            timeout_override=state["config"]["review_timeout"],
            skills=state["config"]["stages"]
            .get("review", {})
            .get("skills", ["trellis-check"]),
        )
        state["history"].append(
            {
                "stage": "review",
                "turn": state["turn"],
                "session_id": sid,
                "gate": result["status"],
            }
        )
        if before != digest(workspace):
            pause(state, "blocked", "Workspace changed during independent review")
            return
        if result["status"] == "passed":
            state["completed"]["review"] = {
                "summary": result["summary"],
                "snapshot": before,
                "turn": state["turn"],
            }
            state["stage"] = "delivery"
            return
        if result["status"] in {"needs_input", "blocked"}:
            pause(state, result["status"], result["question"] or result["summary"])
            return
        state["feedback"] = result["summary"] + "\n" + "\n".join(result["findings"])
        start = STAGES.index(result["return_stage"])
        invalidate(state, STAGES[start])
        for stage in STAGES[start:3]:
            run_agent(source, session, state, stage)
            if state["status"] != "running":
                return
        verify_stage(source, session, state)
        if state["status"] != "running":
            return
    pause(state, "blocked", "独立评审整改达到上限。" + state.get("feedback", ""))


def deliver(session, state):
    if changed_approval(session, state):
        raise ValueError("Approved documents changed before delivery")
    workspace = session / "workspace"
    repo = state["repo"]
    if state["completed"].get("review", {}).get("snapshot") != digest(workspace):
        raise ValueError("Independent review no longer matches delivery contents")
    if controls(workspace) != state["controls"]:
        raise ValueError("Execution controls changed")
    base = api(repo, "commits/" + state["branch"])
    if base["sha"] != state["baseline"]:
        raise ValueError("Base branch advanced; delivery requires reconciliation")
    current = files(workspace)
    old = state["baseline_files"]
    tree = []
    for name in sorted(set(current) | set(old)):
        if (
            name in current
            and hashlib.sha256(current[name]).hexdigest() == old.get(name)
            and (workspace / name).stat().st_mode & 0o111
            == state.get("baseline_modes", {}).get(name)
        ):
            continue
        item = {
            "path": name,
            "mode": "100755"
            if name in current and (workspace / name).stat().st_mode & 0o111
            else "100644",
            "type": "blob",
        }
        if name not in current:
            item["sha"] = None
        else:
            item["sha"] = api(
                repo,
                "git/blobs",
                "POST",
                {
                    "encoding": "base64",
                    "content": base64.b64encode(current[name]).decode(),
                },
            )["sha"]
        tree.append(item)
    if not tree:
        state["completed"]["delivery"] = {
            "summary": "Existing code verified; no new changes to commit"
        }
        pause(
            state,
            "waiting_review",
            "已有材料验证完成，无新增代码改动；请查看评审与验证结果。",
        )
        return
    branch = "codex/full-task-" + str(state["task"]["number"])
    snapshot = digest(workspace)
    if state.get("delivery_snapshot") != snapshot:
        refs = api(repo, "git/matching-refs/heads/" + branch)
        existing = [x for x in refs if x["ref"] == "refs/heads/" + branch]
        previous = state.get("delivery_commit")
        if previous:
            if not existing or existing[0]["object"]["sha"] != previous:
                raise ValueError("Delivery branch changed externally")
        elif existing:
            raise ValueError("Delivery branch already exists; inspect before retrying")
        t = api(
            repo,
            "git/trees",
            "POST",
            {"base_tree": base["commit"]["tree"]["sha"], "tree": tree},
        )
        commit = api(
            repo,
            "git/commits",
            "POST",
            {
                "message": "Deliver #"
                + str(state["task"]["number"])
                + ": "
                + state["task"]["title"],
                "tree": t["sha"],
                "parents": [previous or state["baseline"]],
            },
        )
        state.update(
            delivery_commit=commit["sha"],
            delivery_parent=previous,
            delivery_snapshot=snapshot,
        )
        write_json(session / "state.json", state)
    commit = state["delivery_commit"]
    refs = api(repo, "git/matching-refs/heads/" + branch)
    existing = [x for x in refs if x["ref"] == "refs/heads/" + branch]
    if existing and existing[0]["object"]["sha"] != commit:
        if existing[0]["object"]["sha"] != state.get("delivery_parent"):
            raise ValueError("Delivery branch changed externally")
        api(repo, "git/refs/heads/" + branch, "PATCH", {"sha": commit, "force": False})
    if not existing:
        api(repo, "git/refs", "POST", {"ref": "refs/heads/" + branch, "sha": commit})
    pulls = api(repo, "pulls?state=open&head=" + repo.split("/")[0] + ":" + branch)
    pr = (
        pulls[0]
        if pulls
        else api(
            repo,
            "pulls",
            "POST",
            {
                "title": state["task"]["title"],
                "head": branch,
                "base": state["branch"],
                "draft": True,
                "body": "Closes #"
                + str(state["task"]["number"])
                + "\n\n独立完整流程交付。各阶段记录与验证范围见 Issue 交付卡片。请审查后合入。",
            },
        )
    )
    state.update(pr_url=pr["html_url"], pr_number=pr.get("number"))
    pause(
        state,
        "waiting_review",
        "已创建或更新待审 PR；可在 GitHub 审查合入，或回复具体修改意见继续当前任务。",
    )
    state["completed"]["delivery"] = {"summary": pr["html_url"]}


def report(session, state):
    run_url = (
        "https://github.com/"
        + state["repo"]
        + "/actions/runs/"
        + str(state.get("run_id", ""))
    )
    rows = [
        "<!-- harness-full -->",
        "### 完整研发流程",
        "#" + str(state["task"]["number"]) + " · " + state["status"],
        "| 阶段 | 状态 | 产物 / 说明 |",
        "|---|---|---|",
    ]
    for stage in STAGES[:3]:
        done = state["completed"].get(stage)
        status = (
            (
                {"reuse": "复用已有产物", "not_applicable": "无需执行"}.get(
                    done.get("mode"), "已检查"
                )
            )
            if done
            else (state["status"] if stage == state["stage"] else "尚未完成")
        )
        if stage in STAGES[:2] and stage in state.get("approvals", {}):
            status = "人工已确认"
        elif stage in STAGES[:2] and done:
            status = "等待人工确认"
        elif stage == "development" and state["stage"] in STAGES[2:]:
            status = state["status"] + " · " + state["stage"]
        detail = (done or {}).get("artifact") or (done or {}).get("summary", "")
        rows.append(
            "| "
            + stage
            + " | "
            + status
            + " | "
            + str(detail).replace("|", "/").replace("\n", " ")[:600]
            + " |"
        )
    if state.get("routing"):
        rows += ["", "**入口判别：** " + state["routing"]["summary"]]
        for item in state["routing"].get("decisions", []):
            rows += [
                "- "
                + item["stage"]
                + " · "
                + item["action"]
                + "："
                + item["reason"]
                + "；依据："
                + ", ".join(item["evidence"])
            ]
    public_files = {}
    for stage in STAGES[:3]:
        done = state["completed"].get(stage, {})
        names = set(done.get("artifacts", [])) | set(done.get("evidence", {}))
        names.add(
            state["config"]["stages"][stage]["artifact"].replace(
                "{task}", str(state["task"]["number"])
            )
        )
        for name in sorted(names - {"issue"}):
            path = relative_file(session / "workspace", name)
            if path.is_file() and path.suffix in {
                ".md",
                ".json",
                ".yaml",
                ".yml",
                ".txt",
            }:
                public_files[stage + "/" + name] = path
                content = path.read_text()[:5000]
                if path.suffix != ".md":
                    content = "```" + path.suffix[1:] + "\n" + content + "\n```"
                rows += [
                    "",
                    "<details><summary>" + stage + " · " + name + "</summary>",
                    "",
                    content,
                    "",
                    "</details>",
                ]
    if state.get("reason"):
        rows += ["", state["reason"][:8000]]
    if state.get("last_reply"):
        rows += ["", "### Agent 回复", "", state["last_reply"]]
    if state.get("reply_token") or state["status"] == "paused":
        rows += ["", "直接评论即可提问、补充需求、要求修改或恢复，无需命令和 ID。"]
        if state["status"] == "awaiting_approval":
            rows += [
                "确认当前版本时请明确回复，例如：**这版需求确认通过，继续下一阶段。**"
            ]
    if state.get("pr_url"):
        rows += ["", "交付 PR：" + state["pr_url"]]
    rows += [
        "",
        "[查看本次流水线及各阶段下载包](" + run_url + ")。等待澄清不代表交付完成。",
    ]
    body = "\n".join(rows)
    for private_path in [str(session), str(Path.home())]:
        body = body.replace(private_path, "<private-runtime>")
    public = Path(os.environ.get("FULL_PUBLIC", str(session / "public")))
    public.mkdir(parents=True, exist_ok=True)
    (public / "status.md").write_text(body)
    # Only declared/reused text artifacts, never private runtime state or session files.
    for name, path in public_files.items():
        dest = public / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
    output("public", str(public))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(body + "\n")
    if state.get("comment_id"):
        api(
            state["repo"],
            "issues/comments/" + str(state["comment_id"]),
            "PATCH",
            {"body": body},
        )
    else:
        comment = api(
            state["repo"],
            "issues/" + str(state["task"]["number"]) + "/comments",
            "POST",
            {"body": body},
        )
        state["comment_id"] = comment["id"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=["entry", "requirements", "design", "development", "report"]
    )
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    event = read_json(os.environ["GITHUB_EVENT_PATH"])
    repo = os.environ["GITHUB_REPOSITORY"]
    number, instruction = event_input(
        event, repo, os.environ["GITHUB_ACTOR"], os.environ["GITHUB_EVENT_NAME"]
    )
    ref = os.environ["GITHUB_REF"]
    if not ref.startswith("refs/heads/"):
        raise ValueError("Only same-repository branch executions are supported")
    branch = ref[len("refs/heads/") :]
    sha = os.environ["GITHUB_SHA"]
    scope = hashlib.sha256((repo + "\0" + branch).encode()).hexdigest()[:16]
    storage = Path(os.environ["FULL_STATE_ROOT"])
    if not storage.is_absolute() or storage.resolve().is_relative_to(source.resolve()):
        raise ValueError("State root must be absolute and outside checkout")
    session = storage.resolve() / scope / str(number)
    session.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (session / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state_path = session / "state.json"
        state = read_json(state_path) if state_path.exists() else None
        conversation_only = False
        if args.stage == "entry":
            issue = api(repo, "issues/" + str(number))
            if "pull_request" in issue:
                raise ValueError(
                    "Use an Issue; supply existing branch or PR as task context"
                )
            task = {
                "number": number,
                "title": issue["title"],
                "body": issue.get("body") or "",
            }
            if state is None:
                state = new_state(
                    source, session, task, repo, sha, branch, os.environ["RUNNER_NAME"]
                )
            elif task != state["task"]:
                raise ValueError(
                    "Issue baseline edited; provide changes as a version-bound reply or start a new task"
                )
            if state.get("pr_number"):
                pr = api(repo, "pulls/" + str(state["pr_number"]))
                if pr.get("merged_at") or pr.get("state") == "closed":
                    raise ValueError(
                        "Delivery PR is merged or closed; use a new Issue for another iteration"
                    )
            comment_id = event.get("comment", {}).get("id")
            if comment_id and str(comment_id) in state.get("handled_comments", []):
                state["run_id"] = os.environ["GITHUB_RUN_ID"]
                write_json(state_path, state)
                output("continue", "false")
                print("Comment already handled; no duplicate Agent turn.", flush=True)
                return
            if os.environ["GITHUB_EVENT_NAME"] == "issue_comment" or instruction:
                try:
                    conversation_only = not handle_message(
                        source,
                        session,
                        state,
                        instruction,
                        event,
                        sha,
                        os.environ["RUNNER_NAME"],
                        os.environ["GITHUB_RUN_ID"],
                    )
                    if comment_id:
                        state.setdefault("handled_comments", []).append(str(comment_id))
                except Exception as error:
                    pause(state, "blocked", str(error))
                    state["run_id"] = os.environ["GITHUB_RUN_ID"]
                finally:
                    write_json(state_path, state)
            else:
                begin(
                    state,
                    instruction,
                    sha,
                    os.environ["RUNNER_NAME"],
                    os.environ["GITHUB_RUN_ID"],
                    session,
                )

        else:
            if state is None:
                raise ValueError(
                    "Task state is absent on this Runner; no silent session reset"
                )
            if state["run_id"] != os.environ["GITHUB_RUN_ID"]:
                raise ValueError("Run checkpoint does not match")
            if state["runner"] != os.environ["RUNNER_NAME"]:
                raise ValueError(
                    "This workflow must run on its original persistent Runner"
                )
        try:
            if (
                args.stage == "entry"
                and not conversation_only
                and state["status"] == "running"
                and state["stage"] == "entry"
            ):
                assess_entry(source, session, state)
            if state["status"] == "running" and not conversation_only:
                if args.stage in STAGES[:2] and args.stage == state["stage"]:
                    run_agent(source, session, state, args.stage)
                elif args.stage == "development" and state["stage"] in STAGES[2:]:
                    development(source, session, state)
        except Exception as error:
            pause(state, "blocked", str(error))
        finally:
            write_json(state_path, state)
        try:
            report(session, state)
        finally:
            write_json(state_path, state)
        output(
            "continue",
            "true"
            if state["status"] == "running" and not conversation_only
            else "false",
        )
        if args.stage == "entry":
            for stage in STAGES[:3]:
                output(
                    "run_" + stage,
                    "true"
                    if state["status"] == "running"
                    and not conversation_only
                    and (
                        stage == "development"
                        or stage not in state.get("approvals", {})
                    )
                    else "false",
                )
        output("task", number)
        output("status", state["status"])
        if (
            state["status"] == "blocked"
            and args.stage != "report"
            and not conversation_only
        ):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
