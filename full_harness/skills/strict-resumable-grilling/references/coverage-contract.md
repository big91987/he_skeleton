# Coverage and omission contract

The decision graph records known decisions. The coverage map detects decisions that have not been discovered yet.

## Required coverage map

Record every dimension with status `Unscanned`, `Open`, `Provisional`, `Closed`, or `Not Applicable` and include evidence or the reason it is not applicable.

| Dimension | Scan for |
|---|---|
| Goal and success | Intended outcome, measurable success, business commitment |
| Scope and non-goals | Included behavior, exclusions, phase boundary |
| Stakeholders and users | Affected people, operators, customers, external parties |
| Roles and authority | Responsibility, decision rights, approval, override, permissions |
| Domain objects and lifecycle | Identity, ownership, states, transitions, retention |
| Object provenance and bootstrap | Where prerequisite objects come from; who creates or adopts them; supported UI, API, CLI, declarative configuration, or approved runbook; validation, handoff, change, and retirement |
| Main workflows | Trigger, inputs, outputs, handoffs, completion |
| Exceptions and failure | Invalid input, dependency failure, timeout, partial success, recovery |
| Data and integration | Source of truth, contracts, consistency, privacy, external dependencies |
| Quality attributes | Reliability, availability, performance, security, auditability, cost |
| Operations | Observability, alerting, support, reconciliation, incident ownership |
| Migration and rollout | Compatibility, existing data, staged release, rollback |
| Acceptance and evidence | Testable outcomes, evidence owner, release gate |

Do not create a decision for a dimension already settled by reliable evidence. Cite the evidence and mark it `Closed`.

## Role-clarification matrix

When roles, teams, agents, or organizational responsibilities are in scope, record every role using this matrix:

| Field | Required meaning |
|---|---|
| Purpose | Outcome the role exists to protect |
| Responsibilities | Work and state the role owns |
| Decision rights | Decisions the role can make without escalation |
| Required approvals | Decisions that require another authority |
| Permissions | Data and actions the role may access |
| Inputs | Artifacts, evidence, or events required to act |
| Outputs | Durable artifacts or state changes produced |
| Handoffs | Recipient and acceptance condition |
| Failure ownership | Detection, containment, recovery, and communication duties |
| Escalation | Trigger, destination, and decision deadline |
| Conflict rule | Who decides when responsibilities or recommendations disagree |

A role name plus a responsibility sentence does not close this matrix. Put the highest-impact independent authority and failure boundaries into the next dependency-safe batch.

## Omission audit

Run this audit when the frontier appears empty:

1. Identify a stakeholder who could reject, misuse, operate, or be harmed by the design.
2. Trace one normal case from trigger to durable completion. Start one step before every stated precondition: for each durable object already assumed to exist, identify its source, creator or adopter, supported operation, validation, and handoff into the journey.
3. Trace one failure case through detection, containment, recovery, reconciliation, and communication.
4. Identify one assumption whose failure changes scope or architecture.
5. Identify one authority conflict or permission escalation.
6. Identify one downstream artifact or test that must consume each accepted decision.

Terms such as `preconfigured`, `pre-provisioned`, `external`, `imported`, and `initialized by operations` are omission-audit triggers, not closure evidence. A database edit or one-time migration is not a supported operating interface unless the user explicitly accepts it as the current operating model and the runbook, owner, validation, failure recovery, and change path are documented.

Any newly discovered material gap reopens the interview. Record it before asking.

## Completion gate

The coverage map may be marked complete only when:

- every dimension is `Closed` or `Not Applicable` with evidence;
- every role matrix is complete enough for its current phase;
- every prerequisite object has a closed provenance and bootstrap path, or an explicit external dependency with an owned acceptance boundary;
- no failure path lacks an owner;
- no assumption lacks an owner and validation path;
- no accepted decision lacks an artifact or acceptance mapping;
- the omission audit finds no unresolved material decision;
- the user confirms the final synthesis.
