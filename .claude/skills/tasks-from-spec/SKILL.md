---
name: tasks-from-spec
description: Break an approved spec plan into small OpenCode implementation tasks that each trace to scenarios, acceptance criteria, and verification
user-invocable: true
argument-hint: "docs/specs/<slug>/plan.md"
---

## Instructions

You are creating the task breakdown for spec-driven implementation. The output
must make it possible for OpenCode to implement one small vertical slice at a
time without losing traceability.

### Step 1: Read Inputs

Read:

1. The provided `docs/specs/<slug>/plan.md`
2. The sibling `docs/specs/<slug>/spec.md`
3. `docs/contributing/guides/spec-driven-development.md`

If either spec or plan is missing, stop and ask the user to run `specify` or
`plan-from-spec` first.

### Step 2: Create Tasks

Create or update:

```text
docs/specs/<slug>/tasks.md
```

Each task must include:

- A short action title
- Scenario IDs covered (`S-*`)
- Acceptance criteria covered (`AC-*`)
- Expected files or areas touched
- Verification command or planned test file
- Whether it is independently deployable

### Step 3: Slice Rules

Use small vertical slices. A task is too large if it says "build the feature" or
requires reviewing an unbounded diff.

For example, teams functionality should start with "create team model/API and
owner creation test", not "build teams".

### Step 4: Output Summary

Report:

```markdown
Tasks: docs/specs/<slug>/tasks.md
First implementation task: T-1 <title>
Independent deployable slices: <yes/no summary>
Next: implement T-1, then run `verify-spec docs/specs/<slug>/spec.md`
```

## Rules

- Do not write implementation code during this skill.
- Do not create tasks that lack verification.
- Do not include unrelated cleanup unless it is required by a scenario.
- Mark dependencies between tasks explicitly.
