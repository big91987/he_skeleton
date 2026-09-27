# Light conversation workflow

Open an Issue or reply in natural language. Contributors with write, maintain or admin permission can start the Agent. One message starts one `codex exec` or `codex exec resume`; the same Issue keeps the same native Session.

The Agent reads project entries and selects native Skills progressively. All three stage catalogs are discoverable. Requirements and design produce reviewable files and ask for confirmation. A clear confirmation can advance to the next stage inside that same execution. Questions remain conversation, without a separate classifier or model reviewer. Existing materials can be reused as the stage baseline.

The Agent output has exactly three fields: `next_state`, `message`, and `artifacts`. The input `stage` is the current checkpoint; `next_state` is where the following conversation resumes. Values are `requirements`, `design`, `development`, and `done`. Clarifications, questions, waiting for confirmation and blockers keep the same stage and are explained in the message; they are not separate workflow states. A design confirmation may lead directly to verified completion within one execution.

The controller retains document versions and the original user message as evidence when the Agent advances a stage. It does not run a second intent classifier or ask the Agent to copy approval quotes. A malformed result cannot change the checkpoint. `done` requires a matching real check result; a failed publication retries transport without repeating the Agent call. Existing light Sessions migrate their document records and keep their native Session IDs.

Actions shows `authorize → conversation`. The conversation log and job summary show the actual work and resulting stage. The three stages are not three separate Codex jobs in this template. Issue replies contain the Agent's actual words and expandable documents at useful points; downloads are on the linked run.

The native Stop Hook is registered for the conversation but runs development checks only when the Agent claims development delivery. It checks configured project commands and Python format/lint, and asks the same running Codex to repair failures. Requirements, design and ordinary questions do not run those development checks. There is no additional independent model review in this profile. Passing configured checks proves only their scope.

Owner configuration is `.harness/full.json`: entries, stage Skills/instructions/document paths, checks, time limits. Configure real product checks before development; an empty checks list cannot pass delivery. The full template's entry and review configuration is retained for compatibility but not executed by the light profile.

Private state and Codex sessions live under `FULL_STATE_ROOT/light/<repository-and-branch>/<issue>/`. They are separate from full-template tasks and never uploaded as artifacts. Each turn retains its prompt, raw JSONL, structured result and check logs. Runtime failures retain the workspace/session; send a new comment to resume. A rerun of an already started event does not start a second Codex execution. A completed event can retry publication without another model call. Base-revision changes require reconciliation; this initial profile uses one persistent Runner.

Install from a committed toolbox revision with `python3 scripts/install_light.py <product-checkout> --ref <commit>`. `--ref` defaults to HEAD. Installation preserves owner-edited templates and the existing full workflow. Enable only the chosen workflow for automatic Issue events; disable the other through Actions or explicitly separate their triggers. Commit and push the installed files before trying the workflow.

Try: open an Issue, inspect the document, ask a question, request an edit, then confirm it. Verify that each run has one native Session start/resume and that the Session ID stays the same. Continue through design and development, inspect actual checks and the draft PR. Merge remains a human operation.
