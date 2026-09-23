# Full development workflow: three stages

The independent `harness-full.yml` profile preserves the original `harness.yml`, `harness/loop.py` and `/harness` entry. Do not add the old `harness` label when trying this profile.

## First use

1. Install from a reviewed toolbox commit with `python3 scripts/install_full.py <project-repository> --ref <reviewed-commit>`. Review and commit the resulting files. The new Workflow must be on the default branch for Issue commands to work.
2. Configure one trusted persistent macOS ARM64 Runner with the unique `he-full` label, Python 3.11+, Git, authenticated Codex CLI 0.151.0-compatible native Skills, Stop hooks and exec resume, and `gh`. Set `FULL_STATE_ROOT` outside every checkout. The pilot accepts only repository Owner commands, never fork checkouts.
3. Configure `.harness/full.json` with project entry documents, stage instructions, allowed Skills, handoff artifacts and real check commands. An empty check list cannot pass development. Browser projects may need a Runner-specific `NODE_PATH`; non-web projects use their own actual checks.
4. Create a blank Issue describing the change and existing materials. Comment `/develop` to start. Alternatively add the `harness-full` label or manually run **Full development workflow** with the existing Issue number. Ordinary Issue creation or comments do not start this profile.
5. Read the Issue status card. Answer clarifications using its exact `/develop <token> <answer>` command. A clarification answer is not approval of the resulting document.
6. When the card says it awaits approval, review its expanded documents/data contracts or download the Actions artifact. Copy `/develop <token> approve` to approve that exact revision. To request edits, use `/develop <token> <specific changes>` instead. Repeat this for requirements and design.
7. After design approval, development runs implementation, checks, independent review and repairs automatically, then creates a draft PR. Review and merge the product PR manually. If repository policy disallows Actions-created PRs, delivery reports the restriction and retains its branch; it does not change repository settings.

## What Actions shows

Five Jobs: **entry → requirements → design → development → report**. The three middle Jobs are the business stages; entry restores/routes the task, report publishes status and downloadable material. Completed earlier Jobs are skipped in later runs. The requirement and design Jobs end normally while awaiting a person: a green Job does not mean the entire task has shipped.

| Stage | Work | Completion condition |
| --- | --- | --- |
| requirements | Clarification as needed, scope, complete user journeys, PRD and AC | Human confirms the exact documents |
| design | Necessary architecture, interfaces, data contracts, compatibility and migration | Human confirms the exact documents |
| development | Task breakdown, implementation, actual checks, independent review and bounded repairs | Checks and independent review pass; PR delivered for final human review |

Documents already supplied can be reused. Entry assessment cannot approve them on behalf of a person. A design-not-applicable decision is also shown for confirmation. Existing code still undergoes real verification and independent review. Task breakdown and detailed implementation design are development activities, not separate human gates.

Each confirmation records hashes for every declared/reused artifact, including data contracts. Stale tokens and changed documents cannot use the old confirmation. A development change to an approved baseline invalidates the affected stage and later approvals, returns to that stage, and asks for confirmation again. Reviewers can request the same return. Tests and ordinary code-review defects instead return automatically to development.

## Agent configuration and native Skills

`runner.py` selects the stage and uses one `run_agent()` path. `codex.py` configures native Skills and starts/resumes the working Session. `stop_hook.py` runs checks before accepting completion. `development()` drives the check/review/delivery loop within the single visible development Job.

Configuration version 2 defines requirements, design and development plus read-only entry/review roles:

- `instruction`: stage objective; a native `$skill-name` mention explicitly selects a Skill, including one whose policy forbids implicit invocation.
- `skills`: the allowed toolbox Skill directories for that Agent call; does not inject their bodies.
- `inputs`: project-relative material pointers, with `{task}` for the Issue number. Existing route evidence can replace missing template documents.
- `artifact`: primary handoff artifact. Agent-declared additional artifacts are included in confirmation and downloads when they are supported text formats.
- `review_skills`: independent document reviewer's allowed Skills.
- `checks`: actual command argument arrays, applying to development by default. Use `{evidence}` for transient output. Codes 124/125 mean environmental blockage; other failures request repair.

Native `skills/list` is used locally to discover enabled paths, disable paths outside the allowlist, and verify the result before calling the model. These discovery subprocesses exit; there is no additional permanent service. Bundled Skills and same-name project/personal shadows are not implicitly admitted. Unsupported native behavior blocks execution.

Skills retain their original files and references. The runtime never appends Skill bodies to prompts. The first working call receives task context; subsequent calls send changed instructions, answers, feedback or stage policy. Explicit native Skill mentions deliberately select those particular Skills. Catalog scope is not filesystem isolation and cannot erase prior native Session history.

## State, artifacts and recovery

One repository/branch/Issue owns a persistent working Session and workspace under `FULL_STATE_ROOT`. Entry and independent reviewers use separate read-only Sessions. Stop Hook repair continues the working Session. Waiting for a human ends the current process; their version-bound reply starts a new Actions run and resumes the retained Session. No process stays idle waiting for a person.

Private Session files, prompts and runtime logs remain local. Shared requirements, design, decisions and implementation evidence belong in Git. Issue cards show up to 5,000 characters per declared text document; Actions artifacts provide downloadable copies for 30 days. These copies are not the Session database. No website or Pages publication is required.

This pilot requires the same physical Runner and a fixed execution baseline. If the base branch advances, reconcile the retained task before starting against the new revision. Editing the initial Issue baseline mid-task also blocks; send changes as version-bound replies. After the delivery PR is merged/closed, start a new Issue for further work. GitHub concurrency is not a FIFO task queue; wait for the current command to finish before sending another.

The importer rejects symlinks and credential-like files, and caps 3,000 files, 2 MB per file, 60 MB total. Project `.codex` configuration needs review before use. Owner controls cannot be weakened by the working Agent. This is a trusted-project pilot, not hostile-code isolation, cloud persistence or a production-readiness guarantee.

## Toolbox upgrades

Managed `full_harness/` updates come from a pinned toolbox commit. Owner-edited Workflow, stage configuration, AGENTS and project indexes are preserved. Adoption of the five-Job template is explicit; upgrading only runtime code does not rewrite an Owner Workflow. Version-1 nine-Job configuration can be normalized to the three authoring stages, but old active sessions and old Workflow entry commands are not silently migrated.


### Live Agent logs

Open the Actions run, select the current job, and expand the stage step. Codex JSON events and diagnostics are forwarded live with a `[codex]` prefix while the original `agent.jsonl` remains in private Runner storage. No separate session attachment is needed. Completed runs retain their console logs. Agent output and tool results are visible to users who can read the repository Actions logs; the controller does not print the input prompt or authentication files.


### Python formatting and lint

Runner setup: install `full_harness/requirements.txt` in its execution environment and ensure `ruff` is on the service PATH. The managed `full_harness/ruff.toml` selects the Ruff formatter (88 columns, spaces, double quotes) and E4/E7/E9/F/I lint rules.

During development the Agent runs `python3 full_harness/quality.py fix` and resolves remaining errors. Both the Stop Hook and verification execute `python3 full_harness/quality.py check` without changing product files. Existing-code entry receives the same check. Missing Ruff blocks verification; formatting/lint failures return to the implementation loop. Owner functional checks are still mandatory.

The gate scans product Python files, excluding managed control/runtime directories. Non-Python products do not require Ruff for this gate; configure their language-specific commands (for example Go formatting checks and `go vet`) in the Owner checks. The toolbox runtime is checked separately by its source CI. The Python gate is part of the independent full workflow; the legacy workflow is unchanged.
