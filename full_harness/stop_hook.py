#!/usr/bin/env python3
"""Native Stop gate: check -> continue same session, or checkpoint waiting/blocked.
Independent document reviews run here; code acceptance has a visible review Job.
"""

import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from full_harness.codex import invoke
from full_harness.common import (
    clean_env,
    controls,
    digest,
    read_json,
    relative_file,
    run_process,
    write_json,
)
from full_harness.quality import checks as quality_checks


def review_prompt(source, workspace, context, stage):
    spec = context["config"]["stages"].get(stage, {})
    instruction = (
        spec.get("instruction", "")
        if stage == "review"
        else "仅评审当前阶段的产物，不执行作者阶段工作。"
    )
    contracts = {
        name: {
            "artifact": value.get("artifact"),
            "objective": value.get("instruction", "").replace("$", ""),
        }
        for name, value in context["config"]["stages"].items()
    }
    return (
        "你是独立评审者，不能修改项目文件。按本轮原生 Skill 目录选择适用评审 Skill，按需读取正文和引用。\n"
        + instruction
        + "\n"
        "审查依据是实际任务、需求/决策账本、代码、测试、配置和验证证据；不读取实现者私有对话。"
        "检查是否串通基本用户旅程、遗漏前置对象、绕过产品入口、降低验收标准或伪造完成。"
        "检查可维护性、重复实现和架构偏离。验证报告仅证明记录的范围。"
        "审查设计/规划时不把尚未实现代码当成缺陷，但必须判断本阶段是否足以交接。"
        "发现问题返回 changes 和明确 findings、return_stage；缺用户决策返回 needs_input；环境阻塞返回 blocked。"
        "只有本阶段范围真实符合要求才返回 passed；不得要求低风险变更无意义地扩展文档。\n"
        + json.dumps(
            {
                "stage": stage,
                "task": context["task"],
                "instruction": context.get("instruction", ""),
                "entries": context["config"]["entries"],
                "stage_material_to_review": stage,
                "stages": contracts,
                "baseline": context.get("baseline"),
                "routing": context.get("routing"),
                "checks": context.get("check_results", []),
            },
            ensure_ascii=False,
        )
    )


def evaluate(context_path, payload):
    c = read_json(context_path)
    root = Path(c["workspace"])
    evidence = Path(c["evidence"])
    gate_path = evidence / "gate.json"
    gate = read_json(gate_path) if gate_path.exists() else {"attempts": 0}
    if controls(root) != c["controls"]:
        gate.update(status="blocked", reason="任务修改了受保护的执行配置或规则")
        write_json(gate_path, gate)
        return {}
    for name, expected in c.get("approved_files", {}).items():
        path = relative_file(root, name)
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            write_json(
                gate_path,
                {
                    "status": "needs_input",
                    "reason": "已确认产物发生变化，需重新进入人工确认：" + name,
                },
            )
            return {}
    try:
        result = json.loads(payload.get("last_assistant_message") or "{}")
    except ValueError:
        result = {}
    if result.get("status") in {"needs_input", "blocked"}:
        gate.update(
            status=result["status"],
            reason=result.get("question") or result.get("summary"),
        )
        write_json(gate_path, gate)
        return {}
    gate["attempts"] += 1
    if (
        gate["attempts"] > c["config"]["max_attempts"]
        or time.monotonic() > c["deadline_monotonic"]
    ):
        gate.update(
            status="blocked",
            reason="检查轮数或本阶段时限已达到上限；保留现场，不能宣称完成",
        )
        write_json(gate_path, gate)
        return {}
    errors = []
    check_results = []
    if result.get("status") != "ready":
        errors.append("最终结果必须使用规定 JSON 格式；需要澄清时返回 needs_input")
    artifact = c["config"]["stages"][c["stage"]]["artifact"].replace(
        "{task}", str(c["task"]["number"])
    )
    path = relative_file(root, artifact)
    if not path.is_file() or not path.read_text().strip():
        errors.append(
            "本阶段交接记录缺失或为空："
            + artifact
            + "。引用可复用现有材料，勿重写已接受基线。"
        )
    for name in result.get("artifacts", []):
        if not relative_file(root, name).is_file():
            errors.append("声明的产物不存在：" + name)
    before = digest(root)
    if c["stage"] == "development" and not any(
        set(x.get("stages", ["development"])) & {"development", "verification"}
        for x in c["config"].get("checks", [])
    ):
        gate.update(
            status="blocked",
            reason="项目尚未配置任何实现验证入口；请 Owner 在 full.json 配置，不能由实现者降低标准",
        )
        write_json(gate_path, gate)
        return {}
    checks = list(c["config"].get("checks", []))
    if c["stage"] == "development":
        checks += quality_checks(root)
    for idx, check in enumerate(checks):
        if c["stage"] not in check.get("stages", ["development"]) and not (
            c["stage"] == "development" and "verification" in check.get("stages", [])
        ):
            continue
        log = evidence / f"check-{gate['attempts']}-{idx}.log"
        # Configuration originates in the fixed execution snapshot, not Agent edits.
        argv = [
            x.replace("{workspace}", str(root)).replace("{evidence}", str(evidence))
            for x in check["argv"]
        ]
        env = clean_env()
        if c.get("node_path"):
            env["NODE_PATH"] = c["node_path"]
        try:
            code = run_process(
                argv,
                relative_file(root, check.get("cwd", ".")),
                env,
                log,
                c["config"]["check_timeout"],
            )
        except Exception as error:
            gate.update(
                status="blocked", reason="验证运行异常：" + type(error).__name__
            )
            write_json(gate_path, gate)
            return {}
        check_results.append({"name": check["name"], "code": code, "log": log.name})
        if code in (124, 125):
            gate.update(
                status="blocked",
                reason="环境阻塞或超时：" + check["name"],
                checks=check_results,
            )
            write_json(gate_path, gate)
            return {}
        if code:
            errors.append(check["name"] + " 失败：\n" + log.read_text()[-6000:])
    if before != digest(root):
        errors.append("验证执行期间项目文件变化，须核对后重验")
    if not errors and c["stage"] in {"requirements", "design"}:
        c["check_results"] = check_results
        review, review_id = invoke(
            Path(c["source"]),
            root,
            Path(c["session"]),
            review_prompt(Path(c["source"]), root, c, c["stage"]),
            evidence / f"review-{gate['attempts']}",
            review=True,
            timeout_override=c["config"]["review_timeout"],
            skills=c["config"]["stages"][c["stage"]].get(
                "review_skills", ["reviewing-design-and-plans-cn"]
            ),
        )
        write_json(evidence / f"review-{gate['attempts']}.json", review)
        if before != digest(root):
            errors.append("评审期间项目发生变化，评审失效")
        elif review["status"] == "changes":
            errors.extend(review["findings"] or [review["summary"]])
        elif review["status"] in {"needs_input", "blocked"}:
            gate.update(
                status=review["status"],
                reason=review["question"] or review["summary"],
                review=review,
            )
            write_json(gate_path, gate)
            return {}
        gate["review_session"] = review_id
    if errors:
        gate.update(status="changes", reason="\n".join(errors), checks=check_results)
        write_json(gate_path, gate)
        return {
            "decision": "block",
            "reason": "本阶段检查未通过，请在同一会话整改。不得修改执行配置或降低 AC；确需用户决定则返回 needs_input。\n"
            + gate["reason"],
        }
    gate.pop("reason", None)
    gate.update(
        status="passed", snapshot=digest(root), checks=check_results, artifact=artifact
    )
    write_json(gate_path, gate)
    return {}


if __name__ == "__main__":
    try:
        print(
            json.dumps(
                evaluate(Path(sys.argv[1]), json.load(sys.stdin)), ensure_ascii=False
            )
        )
    except Exception as error:
        try:
            c = read_json(sys.argv[1])
            write_json(
                Path(c["evidence"]) / "gate.json",
                {
                    "status": "blocked",
                    "reason": "Hook failure: " + type(error).__name__,
                },
            )
        finally:
            # The outer controller requires a matching passed gate; a silent hook
            # failure can never turn into stage success.
            print("{}")
