# Full workflow validation

Date: 2026-09-21. Runtime: Codex CLI 0.151.0, local macOS Runner profile.

## Verified

- 42 Python tests passed, including all 27 existing-flow tests. New tests cover actual check failure/retry, protected control changes, missing hooks, absent implementation checks, review rejection, stale replies, owner-only commands, installer ownership, native session recovery after interruption, and idempotent delivery after PR permission failure.
- The new Workflow YAML parses with eight named jobs and independent entry events.
- A real Codex conversation asked two clarification questions and retained both answers and the business name through three calls with one native Session ID.
- A real native Stop Hook rejected a deliberately premature ready result. The same Session created the missing file, reran the unchanged check, and passed on the second gate attempt.
- Real requirements and design stages passed independent reviews. The planning review requested a precise executable test task; the builder repaired its plan within the same Session and passed the next review.

## In progress / not claimed

The opt-in CLI project integration test is still running through implementation and independent acceptance. This document must be updated with its actual outcome before claiming the complete chain passed. GitHub delivery tests above are controlled API tests, not a claim that the experimental repository permits Actions-created PRs. Cloud state persistence, multi-Runner scheduling and hosted product previews are not implemented in this profile.

## Reproduce

```sh
python3 -m unittest discover -s tests -v
python3 tests/integration_stop.py --run-live
python3 tests/integration_full.py --run-live
```

Live tests use an already authenticated Codex installation and consume model quota. They retain private evidence under a generated temporary directory and print its location. They do not upload credentials, private sessions or prompts. The integration product is a command-line reading list, deliberately independent of a web UI.
