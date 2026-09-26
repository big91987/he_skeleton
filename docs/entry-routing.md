# Entry assessment and stage routing

The entry job classifies the task against actual project materials. `full_harness/router.py` owns the inference boundary; `runner.py` validates the result and controls execution. No separate scheduler service or task queue is introduced.

| Input condition | Example route |
|---|---|
| One-line idea, insufficient baseline | Requirements → design/planning as needed → implementation → verification → review |
| Existing applicable PRD/AC | Reuse requirements → fill design/planning gaps → implementation → verification → review |
| Prototype with missing backend | Reuse supported material → design or implementation for the actual gap → verification → review |
| Completed implementation supplied | Reuse applicable prior work → verification → review; repair only if checks or review find problems |

These are examples, not filename-based hard-coded routes. The model must assess whether the material covers the current task. Decisions identify each authoring stage, an action (run/reuse/not_applicable), its reason and relative evidence paths. The controller records hashes and rejects nonexistent or escaping evidence. The model cannot remove configured verification or independent review. All new skips are visible in Actions and the Issue card.

## Future Jev backend: researched, not implemented

Checked TypeSafe's public documentation on 2026-09-21. The console redirects unauthenticated visitors to login. No account setup, API-key collection or Jev inference was performed.

Jev accepts state and typed questions. Choice selects among supplied options, Score evaluates a supplied scale, and Noul estimates the probability of a specified statement. Choice and Score include distributions and confidence; Noul has no separate confidence property. Jev does not generate arbitrary explanatory text or browse a repository on our behalf.

A future integration therefore needs to prepare evidence first, ask narrow questions (for example whether existing acceptance criteria cover the requested behavior), and combine the results using code. Routing explanations can be assembled from decision codes and evidence references. Complex evidence gathering and unresolved reasoning can fall back to the LLM. Do not assume that replacing a model name in the current agentic call is sufficient.

Confidence thresholds must be evaluated against our own labeled tasks, especially false skips. Type safety prevents malformed output; it does not prove that a product judgment is correct. Skip policy, permissions, actual checks, review and native coding Session management remain controller responsibilities.

Official references:

- [Introduction](https://docs.typesafe.ai/introduction)
- [Primitives](https://docs.typesafe.ai/primitives)
- [Confidence](https://docs.typesafe.ai/confidence)
- [Quick start](https://docs.typesafe.ai/introduction/quickstart)
