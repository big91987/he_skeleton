"""Keep final replies chronological and Agent progress in an expanding transcript."""

import hashlib
import html
import json
import re

from .common import read_json, write_json


def publish(api, state, body):
    body = re.sub(r"\[([^\]]+)\]\(<private-runtime>[^)]*\)", r"\1（见下方产物）", body)
    identity = [
        state.get("run_id"),
        state.get("turn"),
        state["stage"],
        state.get("status"),
        body,
    ]
    signature = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False).encode()
    ).hexdigest()
    last = state.get("last_timeline_event", {})
    if last.get("signature") == signature:
        return last["url"]
    sequence = state.get("timeline_sequence", 0) + 1
    marker = f"<!-- harness-event:{sequence}:{signature} -->"
    record = find_comment(api, state, marker)
    if record is None:
        comment = api(
            state["repo"],
            f"issues/{state['task']['number']}/comments",
            "POST",
            {"body": marker + "\n" + body},
        )
        record = {"id": comment["id"]}
    url = f"https://github.com/{state['repo']}/issues/{state['task']['number']}#issuecomment-{record['id']}"
    state["timeline_sequence"] = sequence
    state["last_timeline_event"] = {"signature": signature, "url": url}
    return url


def find_comment(api, state, marker):
    """Recover an interrupted POST using only our bot's exact marker."""
    page = 1
    while True:
        comments = api(
            state["repo"],
            f"issues/{state['task']['number']}/comments?per_page=100&page={page}",
        )
        if not isinstance(comments, list):
            return None
        for comment in comments:
            if comment.get("user", {}).get("type") == "Bot" and comment.get(
                "body", ""
            ).startswith(marker + "\n"):
                return {"id": comment["id"]}
        if len(comments) < 100:
            return None
        page += 1


class AgentReplies:
    """Accumulate Agent progress in one folded comment; leave the final separate."""

    def __init__(self, api, state, record_path, private_paths=()):
        self.api = api
        self.state = state
        self.path = record_path
        self.private_paths = private_paths
        self.record = (
            read_json(record_path) if record_path.exists() else {"messages": {}}
        )
        self.pending = None

    def __call__(self, event):
        kind = event.get("type")
        if kind in {"turn.started", "turn.completed", "turn.failed", "error"}:
            self.record["execution_event"] = event
            self.record["execution_status"] = {
                "turn.started": "执行中",
                "turn.completed": "本轮输出已结束",
                "turn.failed": "执行失败",
                "error": "发生错误，等待执行结果",
            }[kind]
            if self.record.get("comment_id"):
                self.update()
            return
        item = event.get("item") or {}
        if not isinstance(item, dict):
            return
        if kind == "item.completed" and item.get("type") == "agent_message":
            self.flush()
            self.record["message_event"] = event
            text = item.get("text", "")
            try:
                value = json.loads(text)
            except (ValueError, TypeError):
                value = None
            if isinstance(value, dict):
                text = value.get("message", "")
            if isinstance(text, str) and text.strip():
                self.pending = (item["id"], text)
            if item.get("phase") == "commentary" or not isinstance(value, dict):
                self.flush()
        elif (
            kind in {"item.started", "item.updated", "item.completed"}
            and item.get("type") != "agent_message"
        ):
            # Older CLI events omit phase. Further work proves the preceding
            # JSON was intermediate; turn.completed leaves the final pending.
            self.flush()

    def flush(self):
        pending, self.pending = self.pending, None
        if not pending:
            return
        item_id, text = pending
        for path in self.private_paths:
            text = text.replace(str(path), "<private-runtime>")
        self.record["messages"][item_id] = text
        self.update()

    def finish(self, success):
        # Process outcome is separate from native event JSON; never invent a
        # turn.completed event when Codex timed out or exited without one.
        self.record["execution_status"] = "本轮已结束" if success else "执行失败"
        if self.record["messages"]:
            self.update()

    def update(self):
        marker = f"<!-- harness-event:progress:{self.state['run_id']}:{self.state['turn']} -->"
        history = "\n\n---\n\n".join(
            html.escape(message, quote=False)
            for message in self.record["messages"].values()
        )
        if len(history) > 30000:
            history = "更早进展见运行日志。\n\n" + history[-30000:]
        text = next(reversed(self.record["messages"].values()), "")
        latest = html.escape(text.strip().splitlines()[0][:140]) if text else ""
        events = [
            self.record[k]
            for k in ("message_event", "execution_event")
            if k in self.record
        ]
        raw = json.dumps(events, ensure_ascii=False, indent=2)
        for path in self.private_paths:
            raw = raw.replace(str(path), "<private-runtime>")
        raw_block = (
            "<details><summary>最近消息与执行事件（完整 JSON）</summary>\n\n<pre>"
            + html.escape(raw)
            + "</pre>\n\n</details>"
            if len(html.escape(raw)) < 20000
            else "完整事件较长，请查看运行日志及本轮结束后的下载包。"
        )
        status = self.record.get("execution_status", "执行中")
        url = f"https://github.com/{self.state['repo']}/actions/runs/{self.state['run_id']}"
        body = (
            f"{marker}\n**{status}** · 阶段：`{self.state['stage']}`\n\n"
            f"<details><summary>Agent 进展 · {latest}</summary>\n\n"
            f"{history}\n\n</details>\n\n{raw_block}\n\n[运行日志]({url})"
        )
        try:
            write_json(self.path, self.record)
            comment_id = self.record.get("comment_id")
            if not comment_id:
                found = find_comment(self.api, self.state, marker)
                comment_id = found["id"] if found else None
            if comment_id:
                self.api(
                    self.state["repo"],
                    f"issues/comments/{comment_id}",
                    "PATCH",
                    {"body": body},
                )
            else:
                result = self.api(
                    self.state["repo"],
                    f"issues/{self.state['task']['number']}/comments",
                    "POST",
                    {"body": body},
                )
                comment_id = result["id"]
            self.record["comment_id"] = comment_id
            write_json(self.path, self.record)
        except Exception:
            # Progress transport must not stop the Agent. Full text remains in
            # private JSONL and Actions logs; later progress retries this comment.
            print(
                "[harness] Agent 进度暂未同步到 Issue，请查看 Actions 日志。",
                flush=True,
            )
