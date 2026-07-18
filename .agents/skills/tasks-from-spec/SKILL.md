---
name: tasks-from-spec
description: Add or update the tasks section inside an approved executable spec.yml, with each task tracing to scenarios, acceptance criteria, and verification
user-invocable: true
argument-hint: "docs/specs/<slug>/spec.yml"
---

## Instructions

You are creating the task breakdown for spec-driven implementation inside the
same `spec.yml`. The output must make it possible for OpenCode to implement one
small vertical slice at a time without losing traceability.

### Step 1: Read Inputs

Read:

1. The provided `docs/specs/<slug>/spec.yml`
2. The `implementation_plan` section inside that spec
3. `docs/contributing/guides/spec-driven-development.md`

If either the spec or `implementation_plan` is missing, stop and ask the user to
run `specify` or `plan-from-spec` first.

### Step 2: Create Tasks

Create or update the `tasks` key inside:

```text
docs/specs/<slug>/spec.yml
```

Each task must include:

- A short action title
- Scenario IDs covered (`S-*`)
- Acceptance criteria covered (`AC-*`)
- Expected files or areas touched
- Verification command or planned test file
- `verification_ids` or test IDs that gate the task
- Initial `status`, blockers, dependencies, and follow-up task links when known
- File ownership and shared-file ownership
- Whether it is independently deployable

For shared product surfaces, task dependencies must enforce this order: CLI
implementation/testing against the dev server first, npm SDK and pip SDK
parity/testing locally against the dev server second, GitHub Actions CI/daily-test
reproduction only after local CLI and SDK success, web implementation/testing
third, user confirmation fourth, Apple parity/testing last. Do not create an
SDK, web, or Apple task that can start while an earlier required phase is still
pending, unless the spec records an explicit waiver or accepted external blocker.
The CLI and SDK tasks must run real commands/SDK calls against the real dev
API/WebSocket path; mocked API-call tests can be supplemental unit tasks only and
must not satisfy these gates.

Run validation after editing:

```bash
python3 scripts/spec_validate.py docs/specs/<slug>/spec.yml
```

### Step 3: Slice Rules

Use small vertical slices. A task is too large if it says "build the feature" or
requires reviewing an unbounded diff.

For example, teams functionality should start with "create team model/API and
owner creation test", not "build teams".

Plan-like task loop rule: failed required checks must keep the task active,
blocked, or `needs_fix`; they must create or suggest follow-up tasks linked to
the failed `verification_ids` and affected acceptance criteria. Do not create a
task that has no verification path unless it is explicitly a user-confirmed or
manual task.

User confirmation that deployed dev web behavior works and looks correct is a
real task or verification gate when the feature is user-visible. A passing
Playwright `*.spec.ts` task does not unblock Apple parity by itself.

### Step 4: Output Summary

Report:

```markdown
Tasks: docs/specs/<slug>/spec.yml#tasks
First implementation task: T-1 <title>
Independent deployable slices: <yes/no summary>
Validation: <spec_validate result>
Next: write tests for T-1, record red evidence, implement T-1, then run `verify-spec docs/specs/<slug>/spec.yml`
```

## Rules

- Do not write implementation code during this skill.
- Do not create tasks that lack verification.
- Do not include unrelated cleanup unless it is required by a scenario.
- Mark dependencies between tasks explicitly.
- Keep follow-up tasks traceable to the failed required checks that created them.
- Update the Schema V2 handoff so a fresh session can start the first pending task
  without reconstructing chat context.
