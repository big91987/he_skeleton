"""Append immutable Issue events; deduplicate only delivery retries."""

import hashlib
import json
import re


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
    record = None
    if record is None:
        # Recover a successful POST whose checkpoint was interrupted. Only trust
        # our bot's exact marker, never a user-supplied lookalike comment.
        page = 1
        while True:
            comments = api(
                state["repo"],
                f"issues/{state['task']['number']}/comments?per_page=100&page={page}",
            )
            if not isinstance(comments, list):
                break
            found = next(
                (
                    c
                    for c in comments
                    if c.get("user", {}).get("type") == "Bot"
                    and c.get("body", "").startswith(marker + "\n")
                ),
                None,
            )
            if found:
                record = {"id": found["id"]}
                break
            if len(comments) < 100:
                break
            page += 1
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
