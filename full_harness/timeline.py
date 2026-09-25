"""Publish one chronological reply per stage and workflow wake-up."""

import re


def publish(api, state, body):
    stage = state["stage"]
    if stage in {"verification", "review", "delivery"}:
        stage = "development"
    key = str(state.get("run_id", "local")) + ":" + stage
    marker = "<!-- harness-stage:" + key + " -->"
    replies = state.setdefault("stage_replies", {})
    record = replies.get(key)
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
    body = re.sub(r"\[([^\]]+)\]\(<private-runtime>[^)]*\)", r"\1（见下方产物）", body)
    text = marker + "\n" + body
    if record:
        if record.get("body") != text:
            api(
                state["repo"],
                "issues/comments/" + str(record["id"]),
                "PATCH",
                {"body": text},
            )
    else:
        comment = api(
            state["repo"],
            f"issues/{state['task']['number']}/comments",
            "POST",
            {"body": text},
        )
        record = {"id": comment["id"]}
    replies[key] = {"id": record["id"], "body": text}
    return f"https://github.com/{state['repo']}/issues/{state['task']['number']}#issuecomment-{record['id']}"
