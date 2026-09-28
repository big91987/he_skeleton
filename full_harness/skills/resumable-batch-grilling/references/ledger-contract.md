# Durable decision-ledger contract

Use one ledger per interview scope. Keep project-specific content in the ledger, never in the reusable skill.

## Header and checkpoint

```markdown
# <Topic> decision ledger

> Status: Active | Complete | Blocked
> Target artifacts: <paths or identifiers>
> Updated: <timestamp>

## Checkpoint

| Field | Value |
|---|---|
| last_completed_round | ... |
| active_round | ... or none |
| active_question_ids | ... |
| unanswered_ids | ... |
| next_id | D-001 |
| resume_note | ... |
```

## Decision record

Each decision must preserve:

| Field | Meaning |
|---|---|
| ID | Stable, unique, never reused |
| semantic_key | Stable meaning for deduplication |
| question | Exact question shown to the user |
| options | Exact options shown |
| recommendation | Recommended option and reasons |
| user_answer | User's actual answer or correction |
| conclusion | Normalized current rule |
| status | `Proposed`, `Asked`, `Accepted`, `Rejected`, `Conflict`, `Superseded`, `Blocked`, or `Frozen` |
| prerequisites | Decisions that must be settled first |
| descendants | Decisions invalidated when this decision changes |
| supersedes | Replaced decision IDs |
| source | Turn, meeting, document, or dated evidence |
| artifact_mapping | Target sections that consume the conclusion |

## Round record

Record the round ID, ordered question IDs, response received, answer-to-ID mapping, resolved IDs, unanswered IDs, and write-verification result.

## Resume algorithm

```text
read and validate ledger
→ read target artifacts and evidence
→ restore unanswered active-round IDs
→ otherwise compute the dependency-ready frontier
→ remove semantic duplicates
→ select one foundational question or a 3–7 item independent batch
→ allocate IDs and persist as Asked
→ verify and display the persisted questions
→ map and persist answers
→ freeze invalid descendants and recompute the graph
```

## Source precedence

1. User's latest explicit answer.
2. Later accepted decisions that supersede earlier ones.
3. Accepted project decision records.
4. Approved target artifacts.
5. Research evidence.
6. Proposals and recommendations.

A stale artifact is a synchronization gap, not permission to reopen an accepted decision.

## Invariants

- `next_id` is greater than every allocated ID.
- Every displayed question already exists in the active-round checkpoint.
- Every unanswered active-round ID has status `Asked`.
- An accepted decision cannot appear in the pending frontier.
- A superseded decision identifies its replacement.
- A frozen decision identifies the changed prerequisite.
- A batch contains no prerequisite/descendant pair.
- Every completed round has a successful write-verification record.
