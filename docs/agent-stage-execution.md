# Stage-configured native Agent execution

The accepted correction is to preserve native Skill progressive disclosure, constrain available Skills per stage, and resume the working Session using incremental input. Do not copy SKILL.md bodies into model prompts.

```mermaid
flowchart TD
    W[Workflow selects stage] --> C[Read stage instruction, Skills and artifact contract]
    C --> N[Native Codex catalog: enable allowed paths and verify]
    N --> S{Existing working Session?}
    S -->|No| F[Task context + stage instruction]
    S -->|Yes| D[New answer, feedback or stage change]
    F --> A[Codex exec]
    D --> A2[Codex exec resume]
    A --> H[Native Stop Hook checks]
    A2 --> H
    H -->|Changes required| A2
    H -->|Passed| P[Checkpoint and advance]
    H -->|Human decision required| U[Checkpoint and Issue question]
```

`runner.py run_agent()` provides one common execution path for the four authoring stages. It does not implement their business methods. Stage configuration determines the instruction, allowed Skills, input pointers and handoff artifact. Independent entry/review Agents have separate configurable Skill scopes and sessions. `skills.py` adapts native discovery/enablement only; it never parses or injects Skill bodies. `codex.py` owns the CLI call and native Session ID. `stop_hook.py` owns evidence checks and document review before accepting a stage.

See `templates/full/docs/harness-full.md` for configuration and the boundary between current Skill availability and retained Session history.
