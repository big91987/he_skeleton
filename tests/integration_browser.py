"""Opt-in real CLI -> native MCP -> Chromium -> Stop Hook, no GitHub fixtures."""

import json
import sys
import tempfile
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from full_harness.browser import prepare
from full_harness.codex import invoke
from full_harness.common import controls, digest, read_json, write_json

if "--run-live" not in sys.argv:
    raise SystemExit(
        "Use --run-live to install Chromium and use authenticated Codex quota"
    )

root = Path(tempfile.mkdtemp(prefix="harness-browser-live-"))
work = root / "workspace"
(work / "app").mkdir(parents=True)
(work / ".harness").mkdir()
(
    work / "app/index.html"
).write_text("""<!doctype html><html lang="en"><meta charset="utf-8"><title>Browser probe</title>
<body><h1>Reading export probe</h1><label>Book <input id="book"></label>
<button id="add">Add</button><button id="export">Export</button><ul id="books"></ul><p id="status"></p>
<script>
const books=[];
document.querySelector('#add').onclick=()=>{books.push(document.querySelector('#book').value);document.querySelector('#books').textContent=books.join(', ');};
document.querySelector('#export').onclick=()=>{try{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(books)],{type:'application/json'}));a.download='books.json';a.click();URL.revokeObjectURL(a.href);}catch(e){document.querySelector('#status').textContent='Export failed';}};
</script></body></html>""")
plan = [
    {"action": "fill", "label": "Book", "value": "中文书籍"},
    {"action": "click", "role": "button", "name": "Add"},
    {
        "action": "download",
        "role": "button",
        "name": "Export",
        "filename": "books.json",
        "expected": ["中文书籍"],
    },
    {"action": "fail_download"},
    {"action": "click", "role": "button", "name": "Export"},
    {"action": "visible", "text": "Export failed"},
]
write_json(work / "plan.json", plan)
(work / "validation.md").write_text(
    "Real browser probe: Unicode JSON download and visible failure feedback.\n"
)
(work / ".harness/check.py").write_text("""import json
import os
from pathlib import Path
assert os.environ['HARNESS_BROWSER_PROBE'] == 'configured'
assert os.environ['HARNESS_EMPTY_PROBE'] == ''
results=list(Path('docs/05-validation/tasks/1/browser').glob('*/browser.json'))
assert results, 'Native browser evidence missing'
result=json.loads(results[-1].read_text())
assert result['passed'] is True
assert result['downloads'][0]['contents'] == ['中文书籍']
assert result['performed'][-1]['text'] == 'Export failed'
""")
environment = {
    "inherit": [],
    "set": {"HARNESS_BROWSER_PROBE": "configured", "HARNESS_EMPTY_PROBE": ""},
}
prepare(SOURCE, environment)
evidence = root / "evidence"
evidence.mkdir()
cfg = {
    "browser_roots": ["app"],
    "environment": environment,
    "max_attempts": 3,
    "agent_timeout": 360,
    "check_timeout": 30,
    "stages": {"development": {"artifact": "validation.md"}},
    "checks": [
        {
            "name": "browser result and configured environment",
            "argv": [sys.executable, ".harness/check.py"],
        }
    ],
}
context = {
    "source": str(SOURCE),
    "workspace": str(work),
    "session": str(root),
    "evidence": str(evidence),
    "stage": "development",
    "state": {"turn": 1},
    "task": {"number": 1},
    "config": cfg,
    "controls": controls(work),
    "deadline_monotonic": time.monotonic() + 360,
}
write_json(root / "context.json", context)
result, sid = invoke(
    SOURCE,
    work,
    root,
    "Run the native harness_browser.check MCP tool with root app and plan plan.json. Do not launch browsers through shell, change source/plan/checks, or fabricate evidence. Read the returned real browser results. If passed, return ready with validation.md and the tool screenshot/report paths. Otherwise return blocked and explain the actual error.",
    root / "agent",
    browser_context=root / "context.json",
    hook_context=root / "context.json",
    environment=environment,
)
assert result["status"] == "ready", result
receipt = read_json(evidence / "browser.json")
gate = read_json(evidence / "gate.json")
assert receipt and receipt[-1]["passed"] is True
assert result["status"] == "ready"
assert gate["status"] == "passed" and gate["snapshot"] == digest(work)
print(
    json.dumps(
        {"root": str(root), "session": sid, "browser": receipt, "gate": gate}, indent=2
    )
)
