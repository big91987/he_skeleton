"""Render native Codex events for humans without changing retained JSONL."""

import json
import os
import re


def safe(value):
    # Remove terminal controls; never allow event data to emit workflow commands.
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value))


class Console:
    def __init__(self):
        self.actions = os.environ.get("GITHUB_ACTIONS") == "true"
        self.pending = ""

    def text(self, value):
        for line in safe(value).splitlines():
            print("[codex] " + line, flush=True)

    def group(self, title, body):
        title = safe(title).replace("\n", " ")[:180]
        print("::group::" + title if self.actions else "── " + title, flush=True)
        try:
            lines = safe(body).splitlines()
            self.text("\n".join(lines[:100]))
            if len(lines) > 100:
                self.text("… 页面省略其余输出；完整内容保留在原始 agent.jsonl。")
        finally:
            if self.actions:
                print("::endgroup::", flush=True)

    def feed(self, chunk):
        # A tail read can end mid-JSON while Codex is still writing the event.
        self.pending += chunk
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            self.render(line)

    def finish(self):
        if self.pending:
            self.render(self.pending)
            self.pending = ""

    def render(self, line):
        try:
            event = json.loads(line)
        except ValueError:
            self.text(line)
            return
        if not isinstance(event, dict):
            self.text(line)
            return
        kind = event.get("type", "")
        item = event.get("item") or {}
        if not isinstance(item, dict):
            item = {}
        if kind == "thread.started":
            self.text("── Codex 会话已连接 ──")
        elif kind == "turn.started":
            self.text("── 开始本轮执行 ──")
        elif kind in {"error", "turn.failed"}:
            self.text("执行失败：" + str(event.get("message") or event.get("error")))
        elif kind == "turn.completed":
            self.text("── 本轮执行结束 ──")
        elif kind == "item.started" and item.get("type") == "command_execution":
            self.text("执行命令：" + safe(item.get("command", "")).split("\n")[0][:160])
        elif kind == "item.completed":
            self.item(item)
        elif kind not in {"item.started", "item.updated"}:
            self.group("其他运行事件：" + kind, line)

    def item(self, item):
        kind = item.get("type")
        if kind == "agent_message":
            message = item.get("text", "")
            try:
                result = json.loads(message)
            except (ValueError, TypeError):
                result = None
            if isinstance(result, dict) and "summary" in result:
                self.text("Agent：\n" + str(result["summary"]))
                if result.get("status"):
                    self.text("状态：" + str(result["status"]))
                if result.get("question"):
                    self.text("需要你回复：\n" + str(result["question"]))
                details = {
                    k: v
                    for k, v in result.items()
                    if k not in {"summary", "status", "question"} and v
                }
                if details:
                    self.group(
                        "结果详情 / 产物",
                        json.dumps(details, ensure_ascii=False, indent=2),
                    )
            else:
                self.text("Agent：\n" + str(message))
        elif kind == "command_execution":
            code = item.get("exit_code")
            title = f"命令结果 · exit {code} · {item.get('command', '')}"
            if code not in {0, None}:
                self.text(f"命令失败（exit {code}）：{item.get('command', '')}")
            self.group(title, item.get("aggregated_output", ""))
        elif kind == "file_change":
            self.group(
                "文件变更 · " + str(item.get("status", "")),
                json.dumps(item.get("changes", []), ensure_ascii=False, indent=2),
            )
        elif kind in {"error", "warning"}:
            self.text(str(kind) + "：" + str(item.get("message", item)))
        else:
            self.group(
                "工具详情 · " + str(kind),
                json.dumps(item, ensure_ascii=False, indent=2),
            )
