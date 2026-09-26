# Shared implementation guides

Read `AGENTS.md`, `docs/README.md` and the current task's PRD, design and execution plan. Task paths are declared by `.harness/full.json`; do not assume task files are at repository root.

## Pre-Development Checklist

- Inspect current behavior and ownership of the affected code.
- Follow existing conventions. Record a narrow change boundary for non-trivial tasks.
- Follow applicable architecture contracts indexed by the project documentation.

## Quality Check

- Run the configured project checks and task-specific tests.
- Verify complete user paths through real public interfaces; declare unavailable dependencies honestly.
- Preserve compatibility and error handling. Do not weaken acceptance criteria or tests to obtain a pass.
- Update durable interface decisions and project context when confirmed behavior changes.
