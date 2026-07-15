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
- Required assumptions are confirmed, corrected, waived, blocked with a user or
  external dependency, or explicitly scheduled for pre-implementation checking
- Required acceptance criteria have `coverage_status`, `verification_scope`, and
  `verification_ids` when the spec is ready for implementation
- Schema V2 `implementation_state`, approvals, decisions, attempts, and handoff
  records when the spec is newly authored or actively resumed

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
- For shared product surfaces, implementation phase order: CLI against the dev
  server first, GitHub Actions daily-test wiring after dev CLI success, npm SDK
  and pip SDK parity second, web third, user confirmation fourth, Apple last
- Required assumptions that must be checked before implementation and which
  source areas or subagents should verify them
- required assumptions must not be left unchecked when they block implementation
- Acceptance-criteria coverage mapping: each required AC must map to concrete
  `verification_ids`, a user-confirmed/manual check, a waiver path, or a blocker
- Open questions and risks
- Whether a material technical-plan decision needs user approval beyond the
  approved product contract

### Step 4: Keep The Plan Minimal

Avoid speculative architecture. Prefer the smallest vertical slice that can
prove the first scenario. For large features, explicitly identify the first
slice.

If a plan has vague criteria such as "all tests pass" or "no regressions", do
not leave them as final checks. Normalize them into concrete scoped checks such
as backend pytest, CLI, npm SDK, pip SDK, Playwright, Apple build/test, full CI,
manual review, or user confirmation.

For app skills, focus modes, embeds, memory types, provider-backed behavior, and
other cross-client features, the first implementation slice must complete CLI
implementation and testing against the dev server before SDK, web, or Apple work
starts. After dev CLI evidence is green, the same CLI coverage must be moved or
wired into GitHub Actions for daily tests before the plan proceeds to SDK parity.
The CLI evidence must use real CLI commands against the real dev API/WebSocket
path with real auth/test-account state; mocked OpenMates API calls, mocked SDK
clients, stubbed servers, direct function calls, and fixture replay do not
satisfy it. Web work must wait for CLI and required SDK parity. Apple work must
wait for CLI, SDK, web, and user confirmation that deployed dev web behavior
works and looks correct.

Record `approvals.implementation_plan: pending` and stop when the plan introduces
a material architecture, security, privacy, migration, rollout, or external
dependency decision not covered by the approved product contract. Otherwise,
record why a separate technical approval is not required.

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
- Update `handoff` with the next action before finishing this planning step.
- Prefer existing utilities, components, providers, schemas, and architecture.
- If a plan requires a risky dependency, schema, privacy, or auth decision not
  present in the spec, stop and ask.
