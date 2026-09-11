---
name: tasks-from-plan
description: Add or update tasks in an approved executable Plan, tracing each task to Specifications, scenarios, acceptance criteria, and verification
user-invocable: true
argument-hint: "docs/plans/<slug>/plan.yml"
---

## Codex execution boundary

OpenMates Tasks remains the execution source of truth; native OpenMates Plans and
Specs integration is deferred. Preserve the existing repository YAML Plan and PDF
specification approval workflow. Do not create a second manually maintained Task
status database. Ordinary real REST/WebSocket, CLI/SDK and browser verification
runs on the isolated GitHub stack. The separately authorized live signup-email
smoke uses OpenMates CLI and runs only on dev, with isolated test state. It does
not move to GitHub when local credentials are missing. Existing authorization
and explicit user waivers persist; do not restart approval/question rounds or
require videos the user has explicitly declined.

## Instructions

You are creating the task breakdown for Plan-driven implementation. The output
must let Codex implement one small vertical slice at a time without losing
Specification or verification traceability.

### Step 1: Read Inputs

Read the provided `docs/plans/<slug>/plan.yml`, its linked Specifications, and
`docs/contributing/guides/spec-driven-development.md`. If the Plan or linked
Specification references are missing, stop and ask the user to run
`define-specification` or `create-plan` first.

### Step 2: Create Tasks

Create or update `tasks` in the Plan. Each task must include:

- Specification assertion IDs and canonical surfaces changed or proven
- A short action title, scenario IDs (`S-*`), and acceptance criteria (`AC-*`)
- Expected files or areas, verification command or planned test file, and
  `verification_ids`
- Initial status, blockers, dependencies, ownership, and deployability

For shared product surfaces, enforce this dependency order: REST API/WebSocket
on the isolated GitHub stack, CLI, npm and pip SDK parity, web,
deployed Playwright visual smoke for larger web UI, user confirmation, then Apple.
The CLI and SDK tasks must use the real isolated API/WebSocket stack; mocks can only
be supplemental unit tasks.

For required proof videos, add capture, device-scoped WebVTT captions, frame-only
review, and response-media embedding after applicable normal green gates.

Run validation after editing:

```bash
python3 scripts/plan_validate.py docs/plans/<slug>/plan.yml
```

### Step 3: Slice Rules

Use small vertical slices. A task is too large if it says "build the feature" or
requires an unbounded review. Failed required checks keep the task active,
blocked, or `needs_fix` and must create or suggest a traceable follow-up.

### Step 4: Output Summary

```markdown
Tasks: docs/plans/<slug>/plan.yml#tasks
First implementation task: T-1 <title>
Independent deployable slices: <yes/no summary>
Validation: <plan_validate result>
Next: write tests for T-1, record red evidence, implement T-1, then run `verify-plan docs/plans/<slug>/plan.yml`
```

## Rules

- Do not write implementation code during this skill.
- Do not create tasks that lack verification.
- Do not include unrelated cleanup unless required by a scenario.
- Mark task dependencies explicitly and update the Plan handoff.
