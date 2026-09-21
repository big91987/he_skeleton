# Independent full development workflow

This profile adds `harness-full.yml` and `full_harness/`. The existing `harness.yml`, `harness/loop.py`, old task state and `/harness` entry remain independent.

## Owner setup

1. Install with `python3 scripts/install_full.py <project-repository> --ref <reviewed-commit>` from the toolbox checkout. Commit the resulting changes to the product repository. Do not execute unreviewed tool revisions.
2. Review `.harness/full.json`: point `entries` at the existing project indexes and stage artifacts at the existing document layout. Templates seed missing files on first installation; upgrades only replace managed `full_harness/` code. Owner-edited workflow, AGENTS and document indexes are preserved.
3. Configure real verification commands in `checks`, for example `{"name":"tests","argv":["python3","-m","unittest","discover","-s","tests"],"stages":["implementation"]}`. Check programs must write transient evidence under `{evidence}` or ignored runtime directories. Exit 124/125 means environment/timeout; other nonzero results request repairs. A task with no applicable implementation check cannot pass.
4. Use one trusted, persistent macOS ARM64 self-hosted Runner with the unique `he-full` label, Python 3.11+, Git, authenticated Codex CLI supporting native Stop hooks, and `gh`. Set repository variable `FULL_STATE_ROOT` to a private absolute directory outside every checkout. Never expose this Runner to forks or untrusted users. The template only admits repository Owner events; this is deliberately a single trusted-Owner pilot.
5. Allow the workflow token to create draft PRs if organizational policy permits. Otherwise delivery stops with the branch retained; it does not silently change repository permissions. Merge remains a human action.
6. Put the workflow on the default branch to enable Issue events and workflow dispatch. A branch used for manual execution must contain the reviewed toolkit and project checks. Checkout is pinned to the event SHA.

## Entry and stages

An ordinary Issue does not start execution. Owner sends `/develop`, explicitly adds `harness-full`, or selects **Full development workflow → Run workflow** with an existing Issue number. PR numbers and forks are not accepted as execution checkouts; include PR/code references in an Issue. Existing code must be in the selected same-repository execution branch.

Visible jobs: entry → requirements → design → plan → implementation → review → delivery, followed by report. At every entry, existing materials are inspected and reused; completed documents are not blindly regenerated. The first version traverses all gates; it does not silently skip predecessor checks based on a self-reported entry stage.

The stage Agent decides whether clarification is necessary. The Issue card shows its question and a version-bound reply such as `/develop abc1234567 我的回答`. Reply tokens prevent an old reply from satisfying a newer question. Only the Owner can resume. Do not edit the original Issue baseline mid-task; add clarifications through the version-bound reply. After a draft PR is delivered, version-bound feedback on the same Issue resumes implementation in the same Session, reruns acceptance, and updates the existing PR without force-pushing. After that PR is merged or closed, a new task is a new Issue.

`needs_input` pauses normally, not as a false delivery success. `blocked` fails the Job with a reason. Checks feed repair instructions through native Codex Stop hooks within the same Session. Requirements/design/plan get independent document reviews; implementation passes configured checks, then a separate reviewer session evaluates the result. Review findings automatically return to the affected stage, invalidate later stage records, and rerun dependent work within bounded attempts. These returns appear in the task history, not as dynamically added GitHub jobs.

## Documents and memory

AGENTS → project index → accepted project facts and contracts → task PRD/AC/design/plan → validation evidence is the shared knowledge path. Existing MaaS-style paths can be mapped in configuration. Skill bodies are pinned in `full_harness/skills`; prompts name their original path so references can be read. Platform-specific Skills apply only to platform work. The small `.trellis/scripts/get_context.py` is a spec-index helper, not a complete Trellis installation.

One Issue in one execution branch owns a native builder Session; clarification, phases and repairs resume that Session ID. Reviewers use independent Sessions. Runtime state, original prompts, agent output and native Codex session files remain under `FULL_STATE_ROOT/<repository-and-branch-scope>/<issue>/`. These private files are never uploaded. AGENTS, project facts, decisions and task artifacts are durable Git documents. Actions artifacts contain only declared Markdown handoff documents and the public stage card; they are downloadable evidence, not the session database.

The Issue card includes expandable Markdown stage documents (up to 5,000 characters each) and links to the Actions run; each stage uploads a named download package and a step summary. Delivery creates a draft PR with the documents and product code. There is no mandatory website or Pages publish step. Product-specific screenshots or live previews can be added by the Owner; this profile does not yet embed them in the Issue.

## Recovery and limits

This version requires the same physical Runner and retained state directory. Back up that private directory using the organization's secret-handling policy. Moving state between machines, shared cloud storage and concurrent task workers are not implemented. A changed execution revision or edited initial Issue blocks automatic continuation to avoid silently resuming against a different baseline. Retained uncommitted work must be reviewed and reconciled explicitly.

Initial runtime rejects project `.codex` configuration instead of trusting arbitrary hooks. Managed controls are checked for changes, but this is not a hostile-code security boundary: use an isolated Runner OS account and trusted project code. The Agent must not change Owner controls to make checks pass. Timeouts, invalid JSON, missing hooks, changed snapshots and review failures fail closed. Verification only establishes the configured checks and reviewed scope; it is not a production-readiness guarantee.

The pilot imports regular files only, with limits of 3,000 files, 2 MB per file and 60 MB total, excluding dependencies and runtime caches. Symlinks and credential-like files fail closed. Repositories beyond these limits need an explicit import policy before using this profile. GitHub concurrency serializes runs but is not a FIFO task queue: wait for the current command to finish before sending another; a superseded pending run must be submitted again.
