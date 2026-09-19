"""Tool adapter: durable public task context in, structured result out."""
import json
import os
from pathlib import Path
import signal
import subprocess

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["needs_input", "ready"]},
        "summary": {"type": "string"},
        "question": {"type": "string"},
    }, "required": ["status", "summary", "question"],
}


def run_agent(workspace, prompt, evidence, timeout=480, read_only=False):
    evidence.mkdir(parents=True, exist_ok=True)
    schema = evidence / "schema.json"
    contract = json.loads(json.dumps(SCHEMA))
    if read_only:
        contract['properties']['status']['enum'] = ['needs_input']
    schema.write_text(json.dumps(contract))
    result_file = evidence / "result.json"
    result_file.unlink(missing_ok=True)
    # Do not forward Actions/GitHub tokens to the coding process.
    env = {k: v for k, v in os.environ.items()
           if k in {"HOME", "USER", "PATH", "TMPDIR", "LANG", "CODEX_HOME",
                    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                    "http_proxy", "https_proxy", "all_proxy", "no_proxy"}}
    command = ["codex", "exec", "--ignore-user-config", "--ephemeral",
               "--sandbox", "read-only" if read_only else "workspace-write", "-c", 'approval_policy="never"',
               "-c", "features.skip_host_skill_discovery=true",
               "-c", 'model_provider="harness_http"',
               "-c", 'model_providers.harness_http={name="OpenAI HTTPS",wire_api="responses",requires_openai_auth=true,supports_websockets=false}',
               "--skip-git-repo-check", "--json", "--output-schema", str(schema),
               "--output-last-message", str(result_file), "-C", str(workspace), "-"]
    (evidence / "prompt.txt").write_text(prompt)
    with (evidence / "agent.jsonl").open("w") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log,
                                   stderr=log, env=env, text=True, start_new_session=True)
        try:
            process.communicate(prompt, timeout=timeout)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            raise
    if process.returncode != 0 or not result_file.exists():
        raise RuntimeError("Agent execution failed; private runtime log retained locally")
    result = json.loads(result_file.read_text())
    if read_only and result.get("status") != "needs_input":
        raise ValueError("Clarification stage cannot advance to implementation")
    if result.get("status") not in {"needs_input", "ready"}:
        raise ValueError("Invalid agent result")
    if result["status"] == "needs_input" and not result.get("question", "").strip():
        raise ValueError("Agent requested feedback without a question")
    return result
