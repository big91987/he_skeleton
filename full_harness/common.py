"""File checkpoints, bounded subprocesses and project input contracts."""

import hashlib
import json
import os
import re
import signal
import subprocess
import threading
from pathlib import Path

STAGES = ["requirements", "design", "development", "verification", "review", "delivery"]
CONTROL = (
    ".github/",
    ".codex/",
    ".agents/",
    "harness/",
    "full_harness/",
    ".harness/",
    ".trellis/scripts/",
)
IGNORE = {".git", "__pycache__", "node_modules", ".venv", ".pytest_cache"}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text())


def relative_file(root, name):
    path = Path(root) / name
    if (
        Path(name).is_absolute()
        or ".." in Path(name).parts
        or not path.resolve().is_relative_to(Path(root).resolve())
    ):
        raise ValueError("Path must remain inside project: " + name)
    return path


def files(root):
    result = {}
    for p in Path(root).rglob("*"):
        rel = p.relative_to(root)
        if any(x in IGNORE for x in rel.parts):
            continue
        if p.is_symlink():
            raise ValueError("Symlinks need a project import policy: " + str(rel))
        if not p.is_file():
            continue
        if (
            p.name == ".env"
            or (p.name.startswith(".env.") and p.name != ".env.example")
            or p.suffix in {".pem", ".key"}
        ):
            raise ValueError("Credential-like file: " + str(rel))
        if p.stat().st_size > 2_000_000:
            raise ValueError("File exceeds import limit: " + str(rel))
        result[rel.as_posix()] = p.read_bytes()
    if len(result) > 3000 or sum(len(x) for x in result.values()) > 60_000_000:
        raise ValueError("Workspace exceeds import limit")
    return result


def digest(root):
    h = hashlib.sha256()
    for name, data in sorted(files(root).items()):
        h.update(
            name.encode()
            + b"\0"
            + data
            + b"\0"
            + str((Path(root) / name).stat().st_mode & 0o111).encode()
        )
    return h.hexdigest()


def controls(root):
    return {
        n: hashlib.sha256(
            b + str((Path(root) / n).stat().st_mode & 0o111).encode()
        ).hexdigest()
        for n, b in files(root).items()
        if n.startswith(CONTROL)
        or n in {"AGENTS.md", "harness-project.json", "harness-upstream.json"}
    }


def clean_env():
    return {
        k: v
        for k, v in os.environ.items()
        if k
        in {
            "HOME",
            "USER",
            "PATH",
            "TMPDIR",
            "LANG",
            "HTTPS_PROXY",
            "HTTP_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
            "https_proxy",
            "http_proxy",
            "all_proxy",
            "no_proxy",
        }
    }


def stream_log(log, done):
    # Tail the retained file rather than pipe stdout: console forwarding must
    # not change process timeouts, stdin handling or the durable raw evidence.
    with Path(log).open(errors="replace") as reader:
        while True:
            line = reader.readline()
            if line:
                try:
                    # Prefix every line so child output cannot issue Actions commands.
                    print("[codex] " + line.rstrip("\n"), flush=True)
                except (OSError, ValueError):
                    return
            elif done.is_set():
                return
            else:
                done.wait(0.1)


def run_process(argv, cwd, env, log, timeout, prompt=None, *, stream=False):
    with Path(log).open("w") as output:
        p = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE if prompt is not None else subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            text=True,
            start_new_session=True,
        )
        done = threading.Event()
        tail = (
            threading.Thread(target=stream_log, args=(log, done), daemon=True)
            if stream
            else None
        )
        if tail:
            tail.start()
        try:
            p.communicate(prompt, timeout=timeout)
        except BaseException:
            for sig in [signal.SIGTERM, signal.SIGKILL]:
                try:
                    os.killpg(p.pid, sig)
                except ProcessLookupError:
                    pass
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            raise
        finally:
            done.set()
            if tail:
                tail.join(timeout=2)
    return p.returncode


def configuration(source):
    value = read_json(Path(source) / ".harness/full.json")
    if set(value) - {
        "version",
        "entries",
        "stages",
        "checks",
        "max_attempts",
        "agent_timeout",
        "check_timeout",
        "review_timeout",
    }:
        raise ValueError("Unknown full workflow configuration")
    if value.get("version") not in {1, 2}:
        raise ValueError("Unsupported configuration version")
    for name in value["entries"]:
        if not relative_file(source, name).is_file():
            raise ValueError("Project entry missing: " + name)
    # Owner configs from the unpublished nine-job profile retain their existing checks.
    if value["version"] == 1:
        stages = value["stages"]
        dev = stages.pop("implementation")
        plan = stages.pop("plan", {})
        dev["skills"] = list(dict.fromkeys(plan.get("skills", []) + dev["skills"]))
        dev["instruction"] = "拆解可验收任务并持续实现、验证和整改。" + dev.get(
            "instruction", ""
        )
        dev["inputs"] = []
        stages["development"] = dev
        value["version"] = 2
        for check in value.get("checks", []):
            if "stages" in check:
                check["stages"] = list(
                    dict.fromkeys(
                        "development" if x in {"plan", "implementation"} else x
                        for x in check["stages"]
                    )
                )
    defaults = {
        "entry": "核查当前任务和已有材料，判断可复用的阶段产物。",
        "requirements": "明确目标、范围、用户主线与验收标准，必要时澄清，形成 PRD。",
        "design": "依据已确认需求完成必要架构、接口、数据契约与兼容性设计。",
        "development": "拆解任务并持续实现、检查、整改，交付真实验证证据。",
        "review": "独立评审需求、设计、代码与真实验证证据。",
    }
    value["stages"].setdefault("entry", {"skills": []})
    value["stages"].setdefault("review", {"skills": ["trellis-check"]})
    if set(value["stages"]) != {"entry", "review", *STAGES[:3]}:
        raise ValueError("Unknown or missing Agent stage")
    for stage, spec in value["stages"].items():
        if set(spec) - {"instruction", "skills", "inputs", "artifact", "review_skills"}:
            raise ValueError("Unknown Agent stage setting: " + stage)
        spec.setdefault(
            "instruction",
            re.sub(
                r"\$([a-zA-Z0-9_-]+)",
                lambda m: m[0] if m[1] in spec.get("skills", []) else m[1],
                defaults[stage],
            ),
        )
        spec.setdefault("inputs", [])
        spec.setdefault(
            "review_skills",
            ["reviewing-design-and-plans-cn"] if stage in STAGES[:2] else [],
        )
        if not isinstance(spec["instruction"], str) or not spec["instruction"].strip():
            raise ValueError("Stage instruction must be nonempty text")
        for key in ["skills", "review_skills", "inputs"]:
            if not isinstance(spec.get(key), list) or not all(
                isinstance(x, str) and x for x in spec[key]
            ):
                raise ValueError("Stage " + key + " must be a string list")
        for name in spec["skills"] + spec["review_skills"]:
            if not relative_file(
                Path(source) / "full_harness/skills", name + "/SKILL.md"
            ).is_file():
                raise ValueError("Skill missing: " + name)
        for name in spec["inputs"]:
            relative_file(source, name.replace("{task}", "1"))
        if stage not in STAGES[:3]:
            continue
        if not spec.get("artifact"):
            raise ValueError("Stage must declare its handoff artifact")
        relative_file(source, spec["artifact"].replace("{task}", "1"))
    for check in value.get("checks", []):
        if not isinstance(check.get("name"), str) or not check["name"]:
            raise ValueError("Check needs a name")
        if any(x not in STAGES[:4] for x in check.get("stages", ["development"])):
            raise ValueError("Invalid check stage")
        if (
            not isinstance(check.get("argv"), list)
            or not check["argv"]
            or not all(isinstance(x, str) and x for x in check["argv"])
        ):
            raise ValueError("Checks use explicit argument arrays")
        if set(check) - {"name", "argv", "cwd", "stages"}:
            raise ValueError("Unknown check setting")
        relative_file(source, check.get("cwd", "."))
    for name, default, cap in [
        ("max_attempts", 3, 5),
        ("agent_timeout", 600, 1800),
        ("check_timeout", 90, 180),
        ("review_timeout", 480, 480),
    ]:
        value.setdefault(name, default)
        if not isinstance(value[name], int) or not 1 <= value[name] <= cap:
            raise ValueError("Invalid limit: " + name)
    return value
