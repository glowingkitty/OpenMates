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
- Whether it is independently deployable

Run validation after editing:

```bash
python3 scripts/spec_validate.py docs/specs/<slug>/spec.yml
```

### Step 3: Slice Rules

Use small vertical slices. A task is too large if it says "build the feature" or
requires reviewing an unbounded diff.

For example, teams functionality should start with "create team model/API and
owner creation test", not "build teams".

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
