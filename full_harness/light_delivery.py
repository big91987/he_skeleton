"""Draft PR transport after actual checks; no claim of independent model review."""

from full_harness.common import digest, read_json
from full_harness.light import hashes
from full_harness.runner import publish_changes


def deliver(session, state):
    workspace = session / "workspace"
    gate = read_json(
        session / "turns" / str(state["verification"]["turn"]) / "gate.json"
    )
    if gate.get("status") != "passed" or gate.get("snapshot") != digest(workspace):
        raise ValueError("验证记录与交付文件不匹配")
    for approval in state.get("approvals", {}).values():
        if hashes(workspace, approval["files"]) != approval["files"]:
            raise ValueError("已确认文档发生变化，需要重新确认")
    publish_changes(
        session,
        state,
        "codex/light-task-" + str(state["task"]["number"]),
        "轻量对话流程交付。验证记录与实际检查范围见 Issue 和 Actions。未运行额外的独立模型评审；请审查后合入。",
    )
