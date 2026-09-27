"""Live native progressive-disclosure + stage change + Session continuity probe.
Only generated fixtures are sent to the configured Codex service. No product files.
"""

import json
import sys
import tempfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from full_harness.codex import invoke
from full_harness.common import write_json

if "--run-live" not in sys.argv:
    raise SystemExit(
        "Use --run-live: sends generated fixtures to Codex and consumes model quota"
    )
root = Path(tempfile.mkdtemp(prefix="native-skill-live-"))
source = root / "source"
work = root / "work"
home = root / "task"
work.mkdir()
home.mkdir()
(work / ".git").mkdir()
for name, secret in [
    ("stage-alpha", "ALPHA_REFERENCE_9421"),
    ("stage-beta", "BETA_REFERENCE_3862"),
    ("stage-explicit", "EXPLICIT_REFERENCE_5278"),
]:
    p = source / "full_harness/skills" / name
    p.mkdir(parents=True)
    (p / "references").mkdir()
    (p / "references/proof.txt").write_text(secret)
    (p / "SKILL.md").write_text(
        "---\nname: "
        + name
        + "\ndescription: Use when asked to produce the synthetic stage proof.\n---\nTo produce the stage proof, read references/proof.txt relative to this Skill directory. Return the exact proof in summary. Do not modify any files.\n"
    )
explicit = source / "full_harness/skills/stage-explicit/agents"
explicit.mkdir()
(explicit / "openai.yaml").write_text("policy:\n  allow_implicit_invocation: false\n")
print("evidence", root, flush=True)
first, sid = invoke(
    source,
    work,
    home,
    "This is a catalog-only check. Remember the task name BlueShelf. Return ready and report names from the CURRENT enabled Skills catalog. Do not read Skill bodies, references or project files. Do not use tools.",
    root / "first",
    skills=["stage-alpha"],
)
print("first", sid, first, flush=True)
second, resumed = invoke(
    source,
    work,
    home,
    "The stage has changed. Report the names in the CURRENT enabled native Skills catalog, then use the applicable Skill from that current catalog to produce its synthetic stage proof. Return ready; include the remembered task name in summary.",
    root / "second",
    session_id=sid,
    skills=["stage-beta"],
)
assert sid == resumed
assert (
    "BETA_REFERENCE_3862" in second["summary"] and "BlueShelf" in second["summary"]
), second
assert "ALPHA_REFERENCE_9421" not in second["summary"]
assert "stage-beta" in second["summary"] and "stage-alpha" not in second["summary"], (
    second
)
for turn in ["first", "second"]:
    prompt = (root / turn / "prompt.txt").read_text()
    assert (
        "BETA_REFERENCE_3862" not in prompt
        and "To produce the stage proof" not in prompt
    )
third, again = invoke(
    source,
    work,
    home,
    "Now use $stage-explicit to produce its proof. Include the remembered task name. Return ready.",
    root / "third",
    session_id=sid,
    skills=["stage-explicit"],
)
assert (
    again == sid
    and "EXPLICIT_REFERENCE_5278" in third["summary"]
    and "BlueShelf" in third["summary"]
), third
assert "EXPLICIT_REFERENCE_5278" not in (root / "third/prompt.txt").read_text()
write_json(
    root / "verification.json",
    {
        "passed": True,
        "same_session": sid == resumed,
        "first": first,
        "second": second,
        "third": third,
    },
)
print("PASS", sid, json.dumps(second), flush=True)
