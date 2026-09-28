"""Configure Codex's native progressive-disclosure catalog, never read Skill bodies."""

import json
import selectors
import subprocess
import time
from pathlib import Path

from .common import clean_env, relative_file, write_json


def catalog(home, workspace):
    """Use the installed runtime's own discovery; this does not call a model."""
    env = clean_env()
    env["CODEX_HOME"] = str(home)
    process = subprocess.Popen(
        ["codex", "app-server", "--strict-config", "--stdio"],
        cwd=workspace,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)

            def request(number, method, params):
                process.stdin.write(
                    json.dumps({"id": number, "method": method, "params": params})
                    + "\n"
                )
                process.stdin.flush()
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if not selector.select(1):
                        continue
                    line = process.stdout.readline()
                    if not line:
                        raise RuntimeError("Codex skill discovery exited unexpectedly")
                    reply = json.loads(line)
                    if reply.get("id") != number:
                        continue
                    if "error" in reply:
                        raise RuntimeError(
                            "Codex native skill discovery failed: "
                            + str(reply["error"])
                        )
                    return reply["result"]
                raise RuntimeError("Codex native skill discovery timed out")

            request(
                1,
                "initialize",
                {"clientInfo": {"name": "harness_skill_scope", "version": "1"}},
            )
            result = request(
                2, "skills/list", {"cwds": [str(workspace)], "forceReload": True}
            )
            entries = result["data"]
            if len(entries) != 1 or entries[0].get("errors"):
                raise RuntimeError("Invalid native skill catalog: " + str(entries))
            return entries[0]["skills"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()


def configure(home, workspace, source, allowed, config, evidence):
    """Expose native files and disable every discovered path outside the stage allowlist."""
    if not isinstance(allowed, list) or not all(
        isinstance(name, str) for name in allowed
    ):
        raise ValueError("Stage skills must be a list of toolbox skill directories")
    if len(set(allowed)) != len(allowed):
        raise ValueError("Duplicate stage skill")
    root = (source / "full_harness/skills").resolve()
    expected = {
        str(relative_file(root, name + "/SKILL.md").resolve()) for name in allowed
    }
    for path in expected:
        if not Path(path).is_file():
            raise ValueError("Allowed skill does not exist: " + path)
    # Keep references/scripts at their original location and retain stable paths across resume.
    link = home / "skills/harness"
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        if link.resolve() != root:
            raise ValueError("Native skill source changed for this session")
    elif link.exists():
        raise ValueError("Unmanaged native skill directory")
    elif root.is_dir():
        link.symlink_to(root, target_is_directory=True)
    config += "\n[skills.bundled]\nenabled=false\n"
    (home / "config.toml").write_text(config)
    discovered = catalog(home, workspace)
    paths = {str(Path(item["path"]).resolve()) for item in discovered}
    if not expected <= paths:
        raise RuntimeError(
            "Configured skills were not discovered by Codex: " + str(expected - paths)
        )
    for path in sorted(paths):
        config += (
            "\n[[skills.config]]\npath="
            + json.dumps(path)
            + "\nenabled="
            + str(path in expected).lower()
            + "\n"
        )
    (home / "config.toml").write_text(config)
    actual = catalog(home, workspace)
    enabled = [item for item in actual if item.get("enabled")]
    if {str(Path(item["path"]).resolve()) for item in enabled} != expected:
        raise RuntimeError("Native Codex skill allowlist did not take effect")
    # Metadata only: no SKILL.md body or reference text in the Prompt/audit.
    write_json(evidence / "skills.json", {"allowed": allowed, "enabled": enabled})
    return enabled
