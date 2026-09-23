# Project working agreement

Read `docs/README.md` before starting a task. Follow its links to project purpose, current behavior, accepted decisions and applicable task documents. Check the actual code when documents disagree; report the conflict rather than silently choosing a new direction.

- Reuse accepted documents, interfaces and project conventions. Keep this file independent of release numbers.
- Deliver complete basic user journeys, including creation of required objects and failure paths. Direct database edits or fabricated data do not prove a user journey works.
- Persist decisions and material implementation changes in shared documents. Private agent conversations are not the project knowledge base.
- Ask for clarification only when a product decision, material ambiguity or unavailable prerequisite prevents progress. Investigate facts yourself.
- Use `.harness/full.json` for stage handoff paths and verification commands. Its checks and workflow controls are Owner-managed.
- See `docs/harness-full.md` for the independent full workflow, stage outputs and resumption contract.


## Python quality

Use Ruff with 4-space indentation, double quotes, 88-character target line width, and the shared `full_harness/ruff.toml` rules. After editing product Python code, run `python3 full_harness/quality.py fix`, repair remaining errors, then run `python3 full_harness/quality.py check`. The Stop Hook and verification stage run read-only checks independently. Formatting and lint never replace functional tests. Do not weaken quality rules to pass a task. Install the pinned tool using `python3 -m pip install -r full_harness/requirements.txt` in the Runner environment.
