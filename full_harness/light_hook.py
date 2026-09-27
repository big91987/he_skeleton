#!/usr/bin/env python3
"""Only completed development runs checks. No extra Agent/model invocation."""

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from full_harness.common import read_json, write_json
from full_harness.light import validate_result
from full_harness.stop_hook import evaluate as development_check


def evaluate(context_path, payload):
    c = read_json(context_path)
    result = json.loads(payload.get("last_assistant_message") or "{}")
    if result.get("stage") != "development" or not result.get("delivered"):
        return {}
    validate_result(Path(c["session"]), c["state"], result, c["message"], c["sent"])
    # The shared gate is called only as development, so document review / Codex
    # reviewer paths can never execute here.
    path = Path(c["evidence"]) / "development-context.json"
    c["approved_files"] = {
        n: h
        for a in c["state"].get("approvals", {}).values()
        for n, h in a["files"].items()
    }
    if c["state"].get("pending"):
        c["approved_files"].update(c["state"]["pending"]["files"])
    write_json(path, c)
    return development_check(path, payload)


if __name__ == "__main__":
    try:
        print(
            json.dumps(
                evaluate(Path(sys.argv[1]), json.load(sys.stdin)), ensure_ascii=False
            )
        )
    except Exception as error:
        # Outer runner requires a passed snapshot before delivery. Never fake pass.
        print(
            json.dumps({"decision": "block", "reason": str(error)}, ensure_ascii=False)
        )
