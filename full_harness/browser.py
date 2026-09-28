"""Fixed browser checks exposed to stage Agents as one Runner-owned MCP tool."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from full_harness.common import (
    clean_env,
    controls,
    read_json,
    relative_file,
    run_process,
    write_json,
)


def prepare(source, environment=None):
    """Reproducible installation; only called by the controller, never by task code."""
    runtime = Path(source) / "full_harness/browser"
    stamp = runtime / "node_modules/.harness-lock"
    expected = hashlib.sha256((runtime / "package-lock.json").read_bytes()).hexdigest()
    env = clean_env(environment)
    if not stamp.exists() or stamp.read_text() != expected:
        subprocess.run(
            ["npm", "ci", "--ignore-scripts", "--prefix", str(runtime)],
            env=env,
            check=True,
            timeout=180,
        )
        stamp.write_text(expected)
    subprocess.run(
        [str(runtime / "node_modules/.bin/playwright"), "install", "chromium"],
        env=env,
        check=True,
        timeout=180,
    )
    subprocess.run(
        ["node", str(runtime / "check.cjs"), "--probe"], env=env, check=True, timeout=30
    )


def check(context, arguments):
    c = read_json(context)
    workspace = Path(c["workspace"])
    if controls(workspace) != c["controls"]:
        raise ValueError("Protected execution files changed")
    if set(arguments) != {"root", "plan"}:
        raise ValueError("Expected root and plan")
    roots = [
        n.replace("{task}", str(c["task"]["number"]))
        for n in c["config"]["browser_roots"]
    ]
    if arguments["root"] not in roots:
        raise ValueError("Browser root is not configured by the repository owner")
    root = relative_file(workspace, arguments["root"])
    plan = relative_file(workspace, arguments["plan"])
    steps = read_json(plan)
    if not isinstance(steps, list) or len(steps) > 80:
        raise ValueError("Expected at most 80 browser steps")
    evidence = Path(c["evidence"])
    receipt = evidence / "browser.json"
    runs = read_json(receipt) if receipt.exists() else []
    name = f"docs/05-validation/tasks/{c['task']['number']}/browser/{c['stage']}-{c['state']['turn']}-{len(runs) + 1}"
    output = relative_file(workspace, name)
    output.mkdir(parents=True, exist_ok=False)
    script = Path(c["source"]) / "full_harness/browser/check.cjs"
    log = evidence / f"browser-{len(runs) + 1}.log"
    code = run_process(
        ["node", str(script), str(root), str(output), str(plan)],
        workspace,
        clean_env(c["config"].get("environment")),
        log,
        c["config"]["check_timeout"],
    )
    result = (
        read_json(output / "browser.json")
        if (output / "browser.json").exists()
        else {"passed": False, "failure": log.read_text()[-3000:]}
    )
    result["passed"] = code == 0 and result.get("passed") is True
    artifacts = [
        p.relative_to(workspace).as_posix()
        for p in sorted(output.iterdir())
        if p.is_file()
    ]
    record = {
        "root": arguments["root"],
        "plan": arguments["plan"],
        "passed": result["passed"],
        "artifacts": artifacts,
    }
    runs.append(record)
    write_json(receipt, runs)
    return {**record, "result": result}


def serve(context):
    c = read_json(context)
    roots = [
        n.replace("{task}", str(c["task"]["number"]))
        for n in c["config"]["browser_roots"]
    ]
    tool = {
        "name": "check",
        "description": "Run real browser checks on an owner-configured local app/prototype and save desktop/mobile screenshots and results. Use this tool instead of launching a browser in the shell sandbox. plan is a project-relative JSON array: fill/click/visible/absent/reload, viewport(width), key(key), snapshot_storage/unchanged_storage, fail_download, download(role/name or label, expected JSON, optional filename/suffix). No arbitrary JavaScript or shell. Include returned artifacts in your reply; passing proves only these checks.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": False,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "enum": roots},
                "plan": {"type": "string"},
            },
            "required": ["root", "plan"],
            "additionalProperties": False,
        },
    }
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        try:
            method = request["method"]
            if method == "initialize":
                result = {
                    "protocolVersion": request["params"]["protocolVersion"],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "harness_browser", "version": "1.0"},
                }
            elif method == "tools/list":
                result = {"tools": [tool]}
            elif method == "ping":
                result = {}
            elif method == "tools/call" and request["params"]["name"] == "check":
                data = check(context, request["params"].get("arguments", {}))
                result = {
                    "content": [
                        {"type": "text", "text": json.dumps(data, ensure_ascii=False)}
                    ],
                    "isError": not data["passed"],
                }
            else:
                raise ValueError("Unsupported browser method")
            reply = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except Exception as error:
            reply = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": str(error)}],
                },
            }
        print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("context", type=Path)
    serve(parser.parse_args().context)
