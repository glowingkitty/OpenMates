---
status: draft
doc_type: architecture-decision
audience:
  - product
  - contributors
  - technical-users
related_specs:
  - docs/specs/plans-v1/spec.yml
  - docs/specs/tasks-v1/spec.yml
related_issues:
  - https://github.com/glowingkitty/OpenMates/issues/442
  - https://github.com/glowingkitty/OpenMates/issues/447
last_updated: 2026-07-13
---

# Plans V1 Architecture

## Purpose

Plans are privacy-preserving, durable coordination records for complex work.
They provide the goal, scope, ordered steps, acceptance criteria, verification
requirements, and task links that guide a chat beyond its compressed message
history. Tasks remain the execution units; plans define why and how work should
be performed.

This document is the editable product and architecture decision record. The
executable implementation contract, task ledger, and verification evidence live
in `docs/specs/plans-v1/spec.yml`.

## Current Foundation

- `user_plans`, plan-key-wrapper, step, criterion, verification, activity, and
  artifact collection schemas exist.
- Durable plan content is client-encrypted with one key per plan.
- `/v1/user-plans` supports list, create, update, activate, complete, criteria,
  verifications, evidence, drift decisions, and key-wrapper operations.
- Plans can create linked verification tasks.
- The CLI, npm SDK, and Python SDK contain initial plan API contracts.
- Basic `@plan` parsing and generic/code planner routing exist.
- The web app has a disabled Plans route, basic plan cards, an active-chat plan
  preview, and a title/summary detail page.
- Completion currently checks required criteria and verification record status.

## Dependency On Tasks

Plans should not become a second execution engine. The first working Plans
release depends on a proven Task queue architecture:

- A plan links to one primary chat and zero or more project contexts.
- Plan steps create or link Tasks.
- Verification work is represented by normal Tasks with `task_type=verification`.
- A plan cannot complete while required work or verification remains unresolved.

The Tasks CLI queue must be reliable before Plans adds orchestration above it.

## First Working Release

### Goal

Use the CLI to create, inspect, activate, and complete one encrypted plan that
coordinates an existing chat and its encrypted tasks.

### In Scope

- Create/list/update/activate encrypted plans for an existing chat.
- Store and expose ordered plan steps with stable IDs.
- Link work tasks and verification tasks to plan steps.
- Store structured acceptance criteria and verification records.
- Block completion until required criteria and verification records are passed,
  user-confirmed, waived, or explicitly blocked.
- Show plan status, current step, task progress, and completion blockers through
  CLI JSON and human-readable output.
- Support explicit `@plan` routing after the CLI plan contract is stable.

### Explicitly Deferred

- Rich web plan editing and visual timeline UI.
- Automatic natural-language plan creation beyond conservative routing.
- Parallel assumption-investigation sub-chats.
- Automated sandbox test execution and artifact presentation.
- AI evaluator sub-chat UI and complex anti-drift automation.
- Shared/public plans, collaborative plans, and Apple UI.

## Decisions To Make

### Plan Lifecycle

Recommended first lifecycle:

| Status | Meaning |
| --- | --- |
| `draft` | Being prepared or edited |
| `awaiting_confirmation` | Waiting for user approval |
| `active` | Approved but no task is running |
| `executing` | A linked work or verification task is active |
| `blocked` | Required input, verification, or external condition is unresolved |
| `completed` | All required completion conditions are satisfied |
| `archived` | Retained but inactive |

Open decisions:

- Does activation require explicit user confirmation for every plan?
- Can a plan return from `executing` to `active` between tasks?
- Does a failed required check immediately set `blocked`, or return to `active`
  with a new follow-up task?

### Minimum Structured Plan Model

The CLI-first model should settle these fields before UI expansion:

- Goal and scope in/out.
- Ordered phases and steps.
- Assumptions and open questions.
- Decisions, risks, and constraints.
- Acceptance criteria with required/optional status.
- Verification records linked to criteria.
- Linked work and verification Tasks.
- Current phase, step, and task.

Open decision:

- Which fields are first-class records versus encrypted plan-body sections in
  the first release?

### Completion Gate

Recommended first rule: a plan cannot transition to `completed` until every
required criterion is satisfied or waived, and every required verification is
passed, user-confirmed, waived, or explicitly blocked by an accepted external
dependency.

The completion response must enumerate blockers so the CLI can explain exactly
what remains.

### Assumptions

Recommended staged approach:

1. First release stores assumptions and their status in the plan contract.
2. The user or CLI explicitly confirms, corrects, waives, or blocks assumptions.
3. Parallel sub-chat verification is added only after the state model and merge
   rules are proven.

Open decisions:

- Which assumption states are required in the first release?
- Which assumptions must block task execution rather than only plan completion?
- How does a corrected assumption invalidate or update linked tasks and checks?

### Active Plan Context And Anti-Drift

Durable plan content must not depend on chat history because chat compression
can remove older messages. Active execution eventually needs a short-lived,
Vault-encrypted context injected into AI requests.

For the CLI-first release, decide whether this is required immediately or only
after basic plan CRUD and task linking work. If deferred, document that the CLI
is the source of current plan instructions during the interim.

Anti-drift should remain advisory until it is integrated with a proven active
plan context. Corrections must be rendered as system/status messages while being
sent to the LLM as user-role steering messages.

## CLI Contract

The first release should support a workflow equivalent to:

```text
openmates plans create --chat <chat-id> --title "..." --goal "..."
openmates plans step add --plan <plan-id> --title "..."
openmates plans criterion add --plan <plan-id> --text "..." --required
openmates plans verify add --plan <plan-id> --criterion <criterion-id> --kind manual_check
openmates plans activate --plan <plan-id>
openmates plans status --plan <plan-id>
openmates plans complete --plan <plan-id>
```

Final command names remain to be decided. The client may decrypt owner content,
but machine-readable output and backend logs must not expose durable plaintext
outside the local owner environment.

## Verification Strategy

### Deterministic Backend Coverage

- Plan creation persists encrypted content and sparse metadata only.
- Steps, criteria, verifications, and task links retain stable IDs.
- Required completion blockers are complete and explainable.
- Verification tasks link to their plan and criterion.
- Concurrent updates do not overwrite a newer plan version.
- Plan/task status changes move the plan through its selected lifecycle.

### Dev CLI Smoke Flow

1. Create a plan for an existing chat.
2. Add two work steps, two linked tasks, one required criterion, and one required
   verification task.
3. Activate the plan and execute the task queue.
4. Verify completion is refused while the verification is unresolved.
5. Record passing evidence or user confirmation.
6. Complete the plan and inspect the final status and evidence summary.

## Delivery Sequence

1. Finish and prove the Tasks backend/CLI queue.
2. Add Plan CLI CRUD, structured records, task links, and completion blockers.
3. Add deterministic backend and CLI plan smoke coverage.
4. Add active-plan execution context and operational anti-drift only after the
   basic CLI workflow is stable.
5. Add npm and Python SDK parity tests for Tasks and Plans.
6. Build the web Tasks MVP, then the web Plans MVP.
7. Add sandbox checks, assumption sub-chats, rich verification artifacts, and
   sharing as separate follow-up slices.
8. Add Apple parity after the API and web contracts stabilize.

## Related Sources

- `backend/core/api/app/routes/user_plans.py`
- `backend/core/api/app/services/user_plan_service.py`
- `backend/core/api/app/services/directus/user_plan_methods.py`
- `backend/core/directus/schemas/user_plans.yml`
- `backend/apps/ai/processing/plan_focus_routing.py`
- `frontend/packages/openmates-cli/src/client.ts`
- `frontend/packages/ui/src/services/userPlanService.ts`
