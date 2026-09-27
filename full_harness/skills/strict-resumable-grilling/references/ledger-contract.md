# Strict batch decision-ledger contract

Use one durable ledger per interview scope. Keep project facts in the ledger, not in the reusable Skill.

## Header and checkpoint

```markdown
# <Topic> decision ledger

> Status: Active | Complete | Blocked
> Target artifacts: <paths or identifiers>
> Updated: <timestamp>

## Checkpoint

| Field | Value |
|---|---|
| active_batch | R-001 or none |
| active_question_ids | D-001, D-002, D-003 |
| unanswered_ids | ... |
| next_id | D-004 |
| accepted_count | 0 |
| provisional_count | 0 |
| conflict_count | 0 |
| frozen_count | 0 |
| unscanned_coverage_count | 0 |
| single_question_reason | none or explicit dependency reason |
| resume_note | ... |
```

## Decision record

Preserve these fields for every material decision:

| Field | Meaning |
|---|---|
| ID | Stable unique ID, never reused |
| semantic_key | Stable meaning used for deduplication |
| context | Evidence and reason this decision is on the current frontier |
| question | Exact question shown to the user |
| options | Exact mutually exclusive options shown |
| recommendation | Recommended option, reasons, and trade-offs |
| user_answer | User's actual wording |
| conclusion | Normalized current rule |
| status | `Proposed`, `Asked`, `Provisional`, `Accepted`, `Rejected`, `Conflict`, `Superseded`, `Blocked`, or `Frozen` |
| prerequisites | Decisions that must close first |
| descendants | Decisions invalidated when this decision changes |
| supersedes | Replaced decision IDs |
| coverage_dimensions | Coverage rows affected by this decision |
| maturity_checks | Applicable meaning, boundary, authority, failure, counterexample, consistency, impact, and evidence results |
| probes | Follow-up questions and answers under this decision |
| source | User turn, document, system evidence, research, or explicit assumption |
| artifact_mapping | Target sections that consume the conclusion |

## Batch record

For each batch preserve:

- batch ID;
- ordered decision IDs;
- dependency check result;
- comparable-context and answer-shape check;
- `single_question_reason` when size is one;
- exact response received;
- answer-to-ID mapping;
- resolved, provisional, and unanswered IDs;
- write-verification result.

## Batch rules

- Use 3–7 decisions when that many independent frontier items are ready.
- Use 2 when exactly two independent items are ready.
- Use 1 only for a sole ready decision, a prerequisite that blocks all other material items, or a conflict that must be reconciled first.
- A batch contains no prerequisite/descendant pair.
- A follow-up batch may combine independent probes from different provisional decisions.
- Shorthand applies only to IDs in the displayed active batch.

## State rules

- Use `Asked` after the batch is persisted and displayed.
- Use `Provisional` when the user expressed a direction but a material maturity check remains open.
- Use `Accepted` only after all risk-relevant maturity checks close.
- Use `Conflict` when accepted sources disagree and precedence does not resolve them.
- Use `Frozen` for descendants of changed or reopened prerequisites.
- Use `Superseded` instead of deleting replaced decisions.

## Resume algorithm

```text
read and validate ledger
→ read target artifacts and evidence
→ restore unanswered active-batch IDs
→ otherwise scan coverage and compute the dependency-ready frontier
→ select the largest 3–7 item dependency-safe batch
→ persist exact ordered questions before sending
→ map every response to IDs
→ run maturity checks and collect provisional gaps
→ batch independent probes or next-frontier decisions
→ update coverage, freeze descendants, and verify checkpoint
```

## Source precedence

1. User's latest explicit mapped answer.
2. Later accepted decisions that explicitly supersede earlier ones.
3. Accepted project decision records.
4. Approved target artifacts.
5. Verified system or research evidence.
6. Proposals, conventions, and recommendations.

A stale artifact is a synchronization gap, not permission to reopen a settled decision. A convention is a proposal, not evidence of user intent.

## Invariants

- `next_id` is greater than every allocated ID.
- Every displayed question already exists in the verified active batch.
- Every unanswered active-batch ID has status `Asked`.
- Every single-question batch records a valid `single_question_reason`.
- No active batch contains a prerequisite/descendant pair.
- Every `Provisional` decision names its unresolved maturity checks.
- Every `Superseded` decision identifies its replacement.
- Every `Frozen` decision identifies the changed prerequisite.
- Every accepted decision has an artifact mapping or an explicit `none required` reason.
- Ledger completion requires the coverage-contract completion gate.
