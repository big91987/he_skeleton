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

Visible jobs: entry → requirements → design → plan → implementation → verification → review → delivery, followed by report. The read-only model in `full_harness/router.py` assesses the actual task and project materials first. Each authoring stage is marked run, reuse, or not_applicable with reasons and evidence paths. Reuse requires existing material, not just a user's claim. Requirements may be supplied directly by a sufficiently explicit Issue; small changes need not manufacture separate design and planning documents. An existing prototype does not imply that its backend is implemented.

The entry job emits run flags, and the workflow conditions actually skip unnecessary jobs. Skipped predecessors do not prevent later jobs from running. The Issue card shows the assessment and its evidence. Existing code can enter verification directly; configured checks and independent review cannot be skipped by the classifier. Failing supplied code enters the bounded implementation repair loop automatically. If verified existing code requires no changes, the workflow reports its verification result without manufacturing a commit or PR.

Entry ambiguity pauses at entry for a version-bound reply. Human feedback after delivery is assessed again because it may change an earlier requirement or design. The initial inference backend is the existing Codex adapter in read-only mode; Jev has been researched as a future focused decision backend, but is not connected or API-tested.

The stage Agent decides whether clarification is necessary. The Issue card shows its question and a version-bound reply such as `/develop abc1234567 我的回答`. Reply tokens prevent an old reply from satisfying a newer question. Only the Owner can resume. Do not edit the original Issue baseline mid-task; add clarifications through the version-bound reply. After a draft PR is delivered, version-bound feedback on the same Issue resumes implementation in the same Session, reruns acceptance, and updates the existing PR without force-pushing. After that PR is merged or closed, a new task is a new Issue.

`needs_input` pauses normally, not as a false delivery success. `blocked` fails the Job with a reason. Checks feed repair instructions through native Codex Stop hooks within the same Session. Requirements/design/plan get independent document reviews; implementation passes configured checks, then a separate reviewer session evaluates the result. Review findings automatically return to the affected stage, invalidate later stage records, and rerun dependent work within bounded attempts. These returns appear in the task history, not as dynamically added GitHub jobs.

## Documents and memory

AGENTS → project index → accepted project facts and contracts → task PRD/AC/design/plan → validation evidence is the shared knowledge path. Existing MaaS-style paths can be mapped in configuration. Skills and their references are pinned in `full_harness/skills`. The runtime exposes them through native Codex discovery and disables paths outside the current stage allowlist. It never appends Skill bodies to prompts. Platform-specific Skills apply only to platform work. The small `.trellis/scripts/get_context.py` is a spec-index helper, not a complete Trellis installation.

One Issue in one execution branch owns a native builder Session; clarification, phases and repairs resume that Session ID. Reviewers use independent Sessions. Runtime state, original prompts, agent output and native Codex session files remain under `FULL_STATE_ROOT/<repository-and-branch-scope>/<issue>/`. These private files are never uploaded. AGENTS, project facts, decisions and task artifacts are durable Git documents. Actions artifacts contain only declared Markdown handoff documents and the public stage card; they are downloadable evidence, not the session database.

The Issue card includes expandable Markdown stage documents (up to 5,000 characters each) and links to the Actions run; each stage uploads a named download package and a step summary. Delivery creates a draft PR with the documents and product code. There is no mandatory website or Pages publish step. Product-specific screenshots or live previews can be added by the Owner; this profile does not yet embed them in the Issue.

## Recovery and limits

This version requires the same physical Runner and retained state directory. Back up that private directory using the organization's secret-handling policy. Moving state between machines, shared cloud storage and concurrent task workers are not implemented. A changed execution revision or edited initial Issue blocks automatic continuation to avoid silently resuming against a different baseline. Retained uncommitted work must be reviewed and reconciled explicitly.

Initial runtime rejects project `.codex` configuration instead of trusting arbitrary hooks. Managed controls are checked for changes, but this is not a hostile-code security boundary: use an isolated Runner OS account and trusted project code. The Agent must not change Owner controls to make checks pass. Timeouts, invalid JSON, missing hooks, changed snapshots and review failures fail closed. Verification only establishes the configured checks and reviewed scope; it is not a production-readiness guarantee.

The pilot imports regular files only, with limits of 3,000 files, 2 MB per file and 60 MB total, excluding dependencies and runtime caches. Symlinks and credential-like files fail closed. Repositories beyond these limits need an explicit import policy before using this profile. GitHub concurrency serializes runs but is not a FIFO task queue: wait for the current command to finish before sending another; a superseded pending run must be submitted again.


## Agent execution and stage policy

The Workflow selects a stage; `runner.py run_agent()` resumes the same working Agent with that stage's configuration. It is a common call/checkpoint/gate function, not another Agent or a separate work-stage workflow. Requirements, design, plan and implementation differ through `.harness/full.json`:

- `instruction`: this stage's objective; use a native `$skill-name` mention when explicitly selecting a Skill, especially one with `allow_implicit_invocation: false`.
- `skills`: the complete allowed toolbox Skill directory list for this Agent call. This makes Skills available; it does not eagerly invoke them all.
- `inputs`: repository-relative material pointers (`{task}` expands to the Issue number). Reused material referenced by routing can replace absent template documents; these paths are pointers, not mandatory file-existence gates.
- `artifact`: expected handoff record.
- `review_skills`: the separate document reviewer's allowed Skill list. Its scope is not inherited from the working Agent.

Entry assessment and final review also have configurable `instruction` and `skills`. Checks remain explicit executable commands and are selected by their stage setting. The scheduler, actual checks, snapshot validation and delivery stay controller responsibilities; the Skills supply the Agent's working method.

`codex.py` calls native `skills/list` locally (no model call) to discover the installed runtime's catalog, writes `skills.config` path enable/disable entries into the task's generated config, then verifies the effective enabled paths match the allowlist. Bundled system Skills are disabled for these task calls. The same-name Skill in a repository or personal directory is not treated as the configured toolbox Skill. A failed or unsupported discovery/allowlist check blocks execution. `skills.json` records metadata and effective paths privately. Do not set `skip_host_skill_discovery=true`: task Skills must use native discovery.

Codex exposes Skill metadata and loads selected instructions/references progressively. A native `$skill-name` mention intentionally loads that selected Skill; an allowed list alone does not inject every Skill. Explicit-only Skills need an explicit mention in the stage instruction. Keep all supporting files alongside their Skill. Catalog restrictions are not filesystem isolation, and switching stages cannot erase instructions already read into the native Session's history. The new stage instruction replaces the previous working objective.

The first working turn receives the task and project pointers. A resumed turn receives changed answers, feedback, outcomes or stage policy, not the original Issue and every Skill body again. Input checkpoints are trusted for deduplication only after a completed native turn; interrupted calls may conservatively receive context again. Native Stop Hook repairs remain inside the running Codex turn.

This path is tested against Codex CLI 0.151.0 and requires its `app-server skills/list`, path-based Skill enable/disable, bundled-Skill setting, exec resume and native Stop Hook support. It does not add an always-on app-server service: discovery subprocesses exit before model execution.
