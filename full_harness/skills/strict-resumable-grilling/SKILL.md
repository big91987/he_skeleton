---
name: strict-resumable-grilling
description: Use when a plan, design, requirement set, role model, PRD, or architecture needs rigorous multi-round batch clarification, especially when questions must be grouped efficiently without mixing dependencies, losing answers, repeating decisions, or closing with hidden gaps.
---

# Strict Resumable Batch Grilling

## Core principle

Interrogate in dependency-safe batches. Make the batch rigorous, not slow.

```text
NO SINGLE QUESTION WHEN MULTIPLE INDEPENDENT DECISIONS ARE READY.
NO DEPENDENT DECISIONS IN THE SAME BATCH.
NO NEXT BATCH UNTIL EVERY ANSWER IS MAPPED AND VERIFIED.
NO COMPLETION WITHOUT A COVERAGE AUDIT.
```

Read these contracts completely before the first batch:

- `references/ledger-contract.md`
- `references/coverage-contract.md`

## Start or resume

1. Resolve the durable ledger from user instructions or project conventions. Search before creating one.
2. Read the ledger, target artifacts, accepted decisions, and discoverable evidence so factual questions are investigated instead of delegated to the user.
3. Validate stable IDs, active batch, unanswered IDs, statuses, coverage rows, and resume state.
4. Restore an interrupted batch before opening a new frontier.
5. Build or repair the coverage map, then compute every unresolved decision whose prerequisites are closed.

Stop and request a writable location when durable state is required but unavailable. Do not simulate resumability with conversation memory.

## Form the batch

The **frontier** contains all unresolved decisions whose prerequisites are settled.

- Batch 3–7 independent frontier decisions with comparable context and answer shape.
- Batch 2 when exactly two independent decisions are ready.
- Ask one question only when exactly one decision is ready, one foundational prerequisite blocks every other material decision, or one conflict must be reconciled first.
- Record `single_question_reason` whenever a batch contains one question.
- Never place a prerequisite and descendant, alternative formulations of the same rule, or decisions requiring different evidence in one batch.
- Investigate facts from code, documents, systems, or research before allocating a question.

High impact does not by itself require a single-question turn. Separate a question only when its answer changes the options or validity of the remaining frontier.

## Persist before sending

For every batch:

1. Allocate a stable batch ID and stable decision IDs that are never reused.
2. Give each question mutually exclusive options at the same abstraction level, a recommendation, material trade-offs, and an `Unknown / investigate` or `Defer with consequence` option when evidence is insufficient.
3. Persist the exact ordered questions, options, recommendations, prerequisites, semantic keys, coverage dimensions, and status `Asked`.
4. Persist `active_batch`, ordered IDs, unanswered IDs, `next_id`, and any `single_question_reason`.
5. Read the checkpoint back and verify it.
6. Send exactly the persisted batch.

Use concise IDs such as `D-014`. Make it easy to answer with `全部按推荐`, `都是 A`, or `D-014 B，其余按推荐`.

## Map the whole response

After the user responds:

1. Map every answer to an explicit displayed ID; preserve the user's actual wording.
2. Accept shorthand only when the mapping is unambiguous. `全部按推荐` applies to the displayed batch only, never to future batches.
3. Leave unanswered IDs in the active batch and re-present only those IDs.
4. Record normalized conclusions, sources, dependencies, affected artifacts, and material maturity gaps.
5. Mark replaced decisions `Superseded`; never delete history.
6. Freeze descendants affected by reopened, superseded, or conflicting prerequisites.

Do not treat `继续`, silence, urgency, lack of objection, or `按行业惯例` as acceptance. A recommendation is a proposal until the user maps an answer to its ID.

## Keep strictness inside the batch

For each answered decision, check the applicable maturity dimensions:

| Check | Required meaning |
|---|---|
| Meaning | The selected rule is unambiguous. |
| Boundary | Its applicable and excluded scope is clear enough for the current phase. |
| Authority | Decision, execution, approval, observation, and override ownership are not contradictory. |
| Failure | Material inability, exception, or recovery behavior is owned. |
| Counterexample | A realistic failure case does not invalidate the conclusion. |
| Consistency | It does not conflict with accepted decisions or evidence. |
| Impact | Downstream decisions and artifacts are identified. |
| Evidence | The conclusion is labeled as user decision, verified fact, or assumption. |

Set `Accepted` when all risk-relevant checks close. Set `Provisional` when a material check remains open.

Collect independent follow-up probes from all provisional decisions into the next 2–5 item probe batch. Ask a single probe only when one unresolved prerequisite blocks every other probe. Do not convert strictness into serial interrogation.

## Recompute and continue

After each response:

1. Update decision and coverage statuses.
2. Verify answer counts, unanswered IDs, provisional gaps, conflicts, frozen descendants, and checkpoint state.
3. Compute the next dependency-ready frontier.
4. Batch the next independent decisions or probes.
5. Persist and verify before sending.

If mapping, persistence, or verification fails, stop instead of continuing from memory.

## Complete only after omission audit

Before declaring shared understanding, verify:

- every applicable coverage dimension is `Closed` or `Not Applicable` with evidence;
- no decision remains `Asked`, `Provisional`, `Conflict`, `Blocked`, or `Frozen`;
- every accepted decision maps to a consuming artifact or records why none is needed;
- every assumption has an owner and validation path;
- no stakeholder, authority conflict, uncontrolled failure, exception path, or acceptance obligation remains implicit;
- no journey begins from an unexplained durable object: its provenance, bootstrap or adoption path, supported operation, validation owner, and handoff are closed or explicitly owned as an external dependency;
- the user confirms the synthesized understanding.

Only then update target artifacts and mark the ledger `Complete`.

## Quick reference

| Situation | Required behavior |
|---|---|
| 3–7 independent decisions ready | Send one batch |
| Exactly 2 independent decisions ready | Batch both |
| One prerequisite blocks the rest | Ask it alone and record why |
| User says `全部按推荐` | Map recommendations for the displayed batch only |
| Some batch IDs unanswered | Re-present only those IDs |
| Several independent maturity gaps | Batch the follow-up probes |
| Existing answer found in evidence | Cite and close or reconcile; do not re-ask |
| Frontier appears empty | Run coverage and omission audit |

## Rationalizations to reject

| Rationalization | Reality |
|---|---|
| “One at a time is stricter.” | Strictness comes from dependency, maturity, and coverage checks—not user turn count. |
| “These are important, so each deserves a turn.” | Importance does not create a dependency. Batch independent decisions. |
| “The user is in a hurry, so skip the ledger.” | Urgency strengthens the need for exact mapping and recovery. |
| “All recommendations were pre-approved.” | Only displayed batch IDs can be accepted. |
| “The graph is empty, so we are done.” | An incomplete graph can also be empty. Audit coverage first. |
| “The roles are conventional.” | Conventions are proposals; authority and failure ownership still require decisions. |
| “It is preconfigured, so creation is outside the journey.” | Preconfiguration is an operating mode. Its owner, supported operation, validation, handoff, change, and recovery still need closure. |

## Red flags

- A one-question turn while two or more independent frontier decisions exist.
- A batch containing a prerequisite and its descendant.
- Reusing local numbers instead of stable IDs.
- `Accepted` without material maturity checks.
- Sending the next batch before persisting and verifying all current answers.
- Completion based only on an empty frontier.

Any red flag means: stop, repair the frontier or checkpoint, and resume with the largest dependency-safe batch.
