"""Task-level progress across separate Actions executions."""

NAMES = {"requirements": "需求", "design": "设计", "development": "研发"}
STATUSES = {
    "running": "⏳ 进行中",
    "needs_input": "💬 等你澄清",
    "awaiting_approval": "⏸ 等你确认",
    "blocked": "⛔ 受阻",
    "paused": "⏸ 已暂停",
    "waiting_review": "⏸ 等你审查交付",
}


def progress_rows(state):
    current = state["stage"]
    if current in {"verification", "review", "delivery"}:
        current = "development"
    rows = [
        "<!-- harness-full -->",
        "### 任务进度 · #" + str(state["task"]["number"]),
        "",
        "这张卡持续更新，保留跨轮次进度。Actions 中的 Skipped 仅表示该轮不重复执行。",
        "",
    ]
    statuses = {}
    for stage in NAMES:
        if stage in state.get("approvals", {}):
            status = "✅ 已确认"
        elif stage == current:
            status = STATUSES.get(state["status"], state["status"])
        elif stage in state.get("completed", {}):
            status = "✅ 已完成" if stage == "development" else "⏸ 等你确认"
        else:
            status = "○ 未开始"
        statuses[stage] = status
    rows += [" → ".join(NAMES[s] + " " + statuses[s] for s in NAMES), ""]
    if state.get("reason"):
        rows += ["**当前说明：** " + state["reason"][:8000], ""]
    if state["status"] == "awaiting_approval":
        name = NAMES.get(current, current)
        rows += [
            f"**下一步：** 展开下方{name}产物审阅。直接评论“这版{name}确认通过，继续下一阶段”，或提出修改意见。",
            "",
        ]
    elif state["status"] in {"needs_input", "blocked", "paused"}:
        rows += [
            "**下一步：** 根据上方说明直接评论回答、提出修改或要求继续；无需命令和 ID。",
            "",
        ]
    rows += ["| 阶段 | 持续状态 | 产物 | 运行记录 |", "|---|---|---|---|"]
    base = "https://github.com/" + state["repo"] + "/actions/runs/"
    for stage, name in NAMES.items():
        done = state.get("completed", {}).get(stage, {})
        artifact = (
            "展开下方「" + name + "产物」" if done.get("artifact") else "尚无已通过产物"
        )
        run = state.get("stage_runs", {}).get(stage) or done.get("run_id")
        job_url = state.get("stage_job_urls", {}).get(stage)
        links = [f"[阶段日志]({job_url or base + str(run)})"] if job_url or run else []
        approval = state.get("approvals", {}).get(stage, {})
        comment = approval.get("comment_id")
        if comment:
            issue_url = (
                "https://github.com/"
                + state["repo"]
                + "/issues/"
                + str(state["task"]["number"])
            )
            links.append(f"[用户确认]({issue_url}#issuecomment-{comment})")
        elif approval:
            links.append("已记录用户确认")
        rows.append(
            f"| {name} | {statuses[stage]} | {artifact} | {' · '.join(links) or '—'} |"
        )
    return rows
