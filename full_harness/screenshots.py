"""Publish declared screenshots at immutable Git revisions before asking for review."""

import base64
import hashlib
import json
import re
from urllib.parse import quote

from .common import relative_file, write_json


def publish_screenshots(api, session, state, artifacts, stage):
    images = {}
    for name in artifacts:
        if not name.lower().endswith(".png"):
            continue
        path = relative_file(session / "workspace", name)
        data = path.read_bytes()
        if len(data) > 2_000_000 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Screenshot must be a PNG under 2 MB: " + name)
        images[name] = data
    if not images:
        return ""
    if len(images) > 20:
        raise ValueError("At most 20 screenshots per reply")
    repo = state["repo"]
    signature = hashlib.sha256(
        json.dumps(
            {n: hashlib.sha256(b).hexdigest() for n, b in sorted(images.items())},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    cached = state.get("published_screenshots", {})
    if cached.get("signature") == signature:
        commit = cached["commit"]
    else:
        branch = "codex/harness-evidence-" + str(state["task"]["number"])
        refs = api(repo, "git/matching-refs/heads/" + branch)
        head = next(
            (r["object"]["sha"] for r in refs if r["ref"] == "refs/heads/" + branch),
            None,
        )
        message = "Harness screenshots " + signature
        previous = api(repo, "git/commits/" + head) if head else None
        if previous and previous["message"] == message:
            commit = head  # Recover a successful remote update whose response was lost.
        else:
            tree = []
            for name, data in images.items():
                blob = api(
                    repo,
                    "git/blobs",
                    "POST",
                    {"content": base64.b64encode(data).decode(), "encoding": "base64"},
                )
                tree.append(
                    {"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]}
                )
            tree = api(repo, "git/trees", "POST", {"tree": tree})
            saved = api(
                repo,
                "git/commits",
                "POST",
                {
                    "message": message,
                    "tree": tree["sha"],
                    "parents": [head] if head else [],
                },
            )
            commit = saved["sha"]
            if head:
                api(
                    repo,
                    "git/refs/heads/" + branch,
                    "PATCH",
                    {"sha": commit, "force": False},
                )
            else:
                api(
                    repo,
                    "git/refs",
                    "POST",
                    {"ref": "refs/heads/" + branch, "sha": commit},
                )
        state["published_screenshots"] = {"signature": signature, "commit": commit}
        write_json(session / "state.json", state)
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise ValueError("Invalid screenshot commit")
    # Keep repository visibility; never republish private screenshots to public Pages.
    private = api(repo, "")["private"]
    scope = (
        "设计原型"
        if stage == "design"
        else "研发验证"
        if stage == "development"
        else "需求材料"
    )
    body = f"\n\n### [harness] 📸 截图 · {scope}\n\n[harness] 第 {state['turn']} 轮生成的展示材料；截图本身不等于验收通过。\n"
    for name in images:
        url = f"https://github.com/{repo}/blob/{commit}/{quote(name, safe='/')}"
        label = name.replace("[", "\\[").replace("]", "\\]")
        body += f"\n[harness] **{label}** · [打开原图]({url})\n\n"
        if private:
            body += (
                "[harness] 私有仓库图片需登录后通过原图链接查看，未向公开站点发布。\n"
            )
        else:
            body += f"![{label}](https://raw.githubusercontent.com/{repo}/{commit}/{quote(name, safe='/')})\n"
    return body
