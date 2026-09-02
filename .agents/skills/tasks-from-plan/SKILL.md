---
name: tasks-from-plan
description: Add or update tasks in an approved executable Plan, tracing each task to Specifications, scenarios, acceptance criteria, and verification
user-invocable: true
argument-hint: "docs/plans/<slug>/plan.yml"
---

## Instructions

You are creating the task breakdown for Plan-driven implementation. The output
must let OpenCode implement one small vertical slice at a time without losing
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
against the dev server, CLI, npm and pip SDK parity, CI/daily reproduction, web,
deployed Playwright visual smoke for larger web UI, user confirmation, then Apple.
The CLI and SDK tasks must use real dev-server API/WebSocket calls; mocks can only
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
