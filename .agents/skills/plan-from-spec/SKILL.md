---
name: plan-from-spec
description: Add or update the implementation_plan section inside an approved executable spec.yml with traceability to scenarios, acceptance criteria, and tests
user-invocable: true
argument-hint: "docs/specs/<slug>/spec.yml"
---

## Instructions

You are turning an approved executable product spec into a technical
implementation plan inside the same `spec.yml`. This is still pre-code work. Do
not edit product source files during this skill.

### Step 1: Read The Spec And Guide

Read:

1. The provided `docs/specs/<slug>/spec.yml`
2. `docs/contributing/guides/spec-driven-development.md`
3. Relevant architecture docs and existing source patterns referenced by the spec

If the argument is missing or does not point to a spec file, ask for the spec
path.

### Step 2: Validate Spec Readiness

Before writing the plan, confirm the spec has:

- At least one scenario ID (`S-*`)
- At least one acceptance criterion ID (`AC-*`)
- Scope and non-goals
- Tests with assertions and red/green phase metadata

Run:

```bash
python3 scripts/spec_validate.py docs/specs/<slug>/spec.yml
```

If these are missing, stop and run or recommend `specify` first.

### Step 3: Create The Plan

Create or update the `implementation_plan` key inside:

```text
docs/specs/<slug>/spec.yml
```

The plan must include:

- Link to the spec
- Existing patterns and files to reuse
- Technical architecture and boundaries
- Data flow walkthrough with concrete example values
- API/data/UI/privacy/security impacts
- Affected files with reason for each
- Migration/backfill/rollout needs if any
- Observability/logging needs if any
- Verification strategy with exact test commands where known
- Open questions and risks

### Step 4: Keep The Plan Minimal

Avoid speculative architecture. Prefer the smallest vertical slice that can
prove the first scenario. For large features, explicitly identify the first
slice.

### Step 5: Output Summary

Report:

```markdown
Plan: docs/specs/<slug>/spec.yml#implementation_plan
First slice: <short description>
Main files likely touched: <paths>
Verification: <tests or planned tests>
Validation: <spec_validate result>
Next: run `tasks-from-spec docs/specs/<slug>/spec.yml`
```

## Rules

- Do not write implementation code during this skill.
- Every plan section must trace back to scenario or acceptance-criteria IDs.
- Prefer existing utilities, components, providers, schemas, and architecture.
- If a plan requires a risky dependency, schema, privacy, or auth decision not
  present in the spec, stop and ask.
