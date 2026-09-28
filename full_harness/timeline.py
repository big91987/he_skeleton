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


def progress_event(event):
    if not isinstance(event, dict):
        return False
    item = event.get("item") or {}
    return event.get("type") in {
        "thread.started",
        "turn.started",
        "turn.completed",
        "turn.failed",
        "error",
    } or (
        event.get("type") == "item.completed"
        and isinstance(item, dict)
        and item.get("type") == "agent_message"
    )


def folded_chunks(text):
    """Keep all content; bounded escaped chunks fit GitHub's comment limit."""
    chunks, chunk, size = [], [], 0
    for character in text:
        escaped = html.escape(character, quote=False)
        length = len(escaped.encode("utf-8"))
        if size + length > 24000:
            chunks.append("".join(chunk))
            chunk, size = [], 0
        chunk.append(escaped)
        size += length
    chunks.append("".join(chunk))
    return chunks


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
        if "events" not in self.record:
            self.record["events"] = []
            log = self.path.parent / "agent/agent.jsonl"
            if self.path.exists() and log.exists():
                for line in log.read_text().splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if progress_event(event):
                        self.record["events"].append(event)
            else:
                self.record["events"] = [
                    self.record[k]
                    for k in ("message_event", "execution_event")
                    if k in self.record
                ]
        self.pending = None

    def __call__(self, event):
        kind = event.get("type")
        if progress_event(event):
            self.record["events"].append(event)
            write_json(self.path, self.record)
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
            text = item.get("text", "")
            try:
                value = json.loads(text)
            except (ValueError, TypeError):
                value = None
            if isinstance(value, dict):
                text = value.get("message", "")
            if isinstance(text, str) and text.strip():
                self.pending = ("event-" + str(len(self.record["events"])), text)
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
            "[codex] " + message for message in self.record["messages"].values()
        )
        raw = json.dumps(self.record["events"], ensure_ascii=False, indent=2)
        for path in self.private_paths:
            raw = raw.replace(str(path), "<private-runtime>")
        history_parts, raw_parts = folded_chunks(history), folded_chunks(raw)
        status = self.record.get("execution_status", "执行中")
        url = f"https://github.com/{self.state['repo']}/actions/runs/{self.state['run_id']}"
        ids = self.record.setdefault(
            "comment_ids",
            [self.record["comment_id"]] if self.record.get("comment_id") else [],
        )
        try:
            write_json(self.path, self.record)
            for index in range(max(len(history_parts), len(raw_parts))):
                part_marker = (
                    marker if index == 0 else marker[:-4] + f":part:{index + 1} -->"
                )
                suffix = "" if index == 0 else f" · 续 {index + 1}"
                body = f"{part_marker}\n[harness] **{status}** · 阶段：`{self.state['stage']}` · 第 {self.state['turn']} 轮{suffix}\n\n"
                if index < len(history_parts):
                    body += (
                        f"<details><summary>[codex] 本轮累计进展（{len(self.record['messages'])} 条）{suffix}</summary>\n\n"
                        + history_parts[index]
                        + "\n\n</details>\n\n"
                    )
                if index < len(raw_parts):
                    body += (
                        f"<details><summary>[codex] 本轮累计原始事件（完整 JSON）{suffix}</summary>\n\n<pre>"
                        + raw_parts[index]
                        + "</pre>\n\n</details>\n\n"
                    )
                body += f"[harness] [运行日志]({url})"
                if max(len(history_parts), len(raw_parts)) > 1:
                    body += "\n\n[harness] 完整内容超过单条评论容量，按本轮编号分段保留；JSON 按顺序拼接即为完整内容。"
                comment_id = ids[index] if index < len(ids) else None
                if not comment_id:
                    found = find_comment(self.api, self.state, part_marker)
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
                if index == len(ids):
                    ids.append(comment_id)
                self.record["comment_id"] = ids[0]
                write_json(self.path, self.record)
        except Exception:
            # Retry transport without rerunning the Agent or dropping its history.
            print(
                "[harness] Agent 进度暂未同步到 Issue，请查看 Actions 日志。",
                flush=True,
            )
