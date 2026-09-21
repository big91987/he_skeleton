# Full workflow validation

Date: 2026-09-21. Runtime: Codex CLI 0.151.0, local macOS Runner profile.

## Verified

- 55 Python tests passed, including all 27 existing-flow tests. New tests cover actual check failure/retry, protected control changes, missing hooks, absent implementation checks, review rejection, stale replies, owner-only commands, installer ownership, native session recovery after interruption, and idempotent delivery after PR permission failure.
- The new Workflow YAML parses with nine named jobs and independent entry events.
- A real Codex conversation asked two clarification questions and retained both answers and the business name through three calls with one native Session ID.
- A real native Stop Hook rejected a deliberately premature ready result. The same Session created the missing file, reran the unchanged check, and passed on the second gate attempt.
- Real requirements and design stages passed independent reviews. The planning review requested a precise executable test task; the builder repaired its plan within the same Session and passed the next review.

- The CLI integration reached delivery after requirements, design, planning, implementation and independent review. An implementation time-limit stop retained the same native Session; an explicit recovery instruction resumed it and passed the unchanged Owner check (seven real CLI assertions) and the generated eight-test suite.
- The independent reviewer passed code/contract review and read-only supplementary CLI checks. It could not rerun the entire suite because its read-only sandbox disallowed temporary test storage; its report disclosed that limitation and relied on the matching successful fixed check evidence. This is not a claim of a second independent full test execution.
- The clock guard now uses a monotonic deadline, matching subprocess timeout accounting; a regression test covers a wall-clock jump.
- The reading_list integration branch passed its existing 16-action browser regression with real Chromium. Product code and the original workflow were not changed.

## Not claimed

The GitHub delivery tests are controlled API tests, not a live Actions-to-PR delivery demonstration. The repository currently disables Actions-created PRs; the delivery controller retains its branch and reports a blocker if that restriction applies. Cloud state persistence, multi-Runner scheduling and hosted product previews are not implemented in this profile.

## Reproduce

```sh
python3 -m unittest discover -s tests -v
python3 tests/integration_stop.py --run-live
python3 tests/integration_full.py --run-live
```

Live tests use an already authenticated Codex installation and consume model quota. They retain private evidence under a generated temporary directory and print its location. They do not upload credentials, private sessions or prompts. The integration product is a command-line reading list, deliberately independent of a web UI.

## Entry routing update

Additional offline tests cover idea entry, PRD reuse, existing-code entry, absent or escaping evidence paths, forbidden stage selection, clarification pauses, real verification of supplied code, bounded repair on failure and missing Owner checks. The nine-job YAML has explicit skip-safe dependencies and per-stage flags.

A new live Codex assessment of the retained CLI fixture was not executed: automatic approval review rejected sending those project files to the external model without explicit approval. Earlier live Session, Hook and stage results above do not establish that the new classifier has been live-tested. No Jev API call was made.
