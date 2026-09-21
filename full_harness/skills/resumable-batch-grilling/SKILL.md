---
name: resumable-batch-grilling
description: Use when stress-testing or aligning a plan, design, requirement set, PRD, or architecture across multiple decision rounds where batching, interruptions, context loss, repeated questions, or durable handoff are concerns.
---

# Resumable Batch Grilling

## Core principle

Interview along a decision graph. Batch only independent decisions with settled prerequisites.

```text
NO QUESTION WITHOUT A DURABLE ID.
NO NEW FRONTIER BEFORE THE CURRENT ROUND IS PERSISTED AND VERIFIED.
```

Use `references/ledger-contract.md` as the required state contract.

## Start or resume

1. Resolve the ledger from user or project conventions, searching before creation.
2. Read the ledger, target artifacts, and evidence.
3. Validate the checkpoint; resume only unanswered IDs from an interrupted round.
4. Reconcile by meaning. Never re-ask an accepted decision because artifacts changed.
5. If accepted sources conflict, mark `Conflict` and ask one reconciliation question.

Stop before grilling if no durable writable location exists.

## Build the decision graph

The **frontier** contains unresolved decisions with settled prerequisites.

- Investigate facts available from code, documents, systems, or research; do not ask the user.
- Give every question mutually exclusive options, a recommendation, and reasons.
- Ask a high-impact, ambiguous, or foundational decision alone.
- Batch 3–7 independent frontier decisions when they have comparable context and answer shape.
- Never place a decision and its prerequisite in the same batch.
- Freeze downstream decisions when a prerequisite is reopened, superseded, or conflicted.

Before allocating an ID, check for the same business rule, object transition, permission boundary, failure behavior, or quality commitment. Link instead of repeating.

## Checkpoint before sending

Before displaying a batch:

1. Allocate stable IDs that are never reused.
2. Persist the exact question, options, recommendation, rationale, prerequisites, semantic key, and status `Asked`.
3. Persist `active_round`, ordered and unanswered IDs, and the next ID.
4. Read the checkpoint back and verify it.
5. Send exactly the persisted batch.

## Map and persist answers

Map every answer to explicit IDs. Accept “全部按推荐”, “都是 A”, or “除 D-014 外其余选 A” only when unambiguous.

Do not treat “继续”, silence, or an explanation without a choice as acceptance.

After each response:

1. Resolve answered IDs and preserve the user's actual wording.
2. Record normalized conclusions, rationale, source, dependencies, and artifact mappings.
3. Mark replaced decisions `Superseded`; never delete history.
4. Recompute the graph and pending frontier.
5. Read back and verify counts, statuses, IDs, and resume state before the next batch.

If mapping, persistence, or verification fails, stop rather than continue from memory.

## Finish

Complete only when no `Asked`, `Conflict`, frozen descendant, or silent assumption remains and the user confirms shared understanding. Then synchronize target artifacts and record the final checkpoint.

## Red flags

- Asking the user something that can be investigated.
- Sending a batch before its checkpoint exists.
- Batching dependent or foundational decisions for speed.
- Reusing local numbers each round.
- Treating recommendations or “继续” as acceptance.
- Updating target artifacts while the decision state is unresolved.

Any red flag means: load and repair the ledger, then resume.
