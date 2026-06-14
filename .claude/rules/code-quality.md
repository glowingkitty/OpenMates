---
description: Maintainability guardrails for AI-generated code and refactors
globs:
  - "**/*.py"
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.svelte"
  - "**/*.js"
  - "**/*.swift"
---

# Code Quality And Technical Debt Guardrails

Prefer the smallest behavior-preserving change that reduces future maintenance
cost. Do not add new architecture, abstractions, compatibility layers, or helper
names unless they remove real duplication or isolate a responsibility that is
already too large.

## Large Files

- Do not add new source files over 800 lines.
- Avoid adding responsibilities to source files over 2,500 lines. Extract a
  focused helper, child component, service, or schema instead.
- For files over 4,000 lines, first look for a behavior-preserving extraction
  seam before editing inline.
- Never rewrite a large file wholesale unless the user explicitly approves it.

## Duplication

- Search for existing shared utilities, BaseSkill behavior, embed primitives,
  settings elements, and schema types before adding new logic.
- Backend skills must not copy provider/error/result boilerplate across apps;
  move repeated behavior to `BaseSkill`, `backend/shared/python_utils/`,
  `backend/shared/python_schemas/`, or `backend/shared/providers/`.
- Frontend embed previews/fullscreens should use shared UnifiedEmbed primitives
  instead of repeating layout and lifecycle code.

## Deterministic Scripts And Audits

- When you uncover a recurring bug pattern, flaky test pattern, security/privacy
  risk, provider metadata drift, code-quality issue, or OpenCode workflow that
  repeatedly consumes inference, ask whether a deterministic script can prevent
  or detect it.
- Prefer updating an existing audit, guard, test helper, or repo script before
  adding a new script. New scripts should be high-signal, cheap to run, and easy
  to invoke from skills or hooks.
- Wire deterministic checks into hooks only when they are path-scoped and
  low-noise. If a full-repo scan would fail on legacy debt, make the hook check
  newly changed lines/files and expose `--all` for on-demand cleanup.
- Every new deterministic script should include focused tests or fixtures that
  cover both a failing example and an allowed/clean example.
- Do not use deterministic scripts to hide errors or replace product tests; use
  them to catch repeatable contracts before humans or agents spend tokens
  rediscovering the same issue.

## Error Handling

- Avoid new broad `except Exception` or broad `catch` blocks inside business
  logic. Use typed/expected exceptions where possible.
- If a boundary must catch broadly, log enough context and re-raise or return an
  explicit typed error. Never hide failures with silent fallbacks.

## Suppressions And TODOs

- Do not add `@ts-ignore`, `eslint-disable`, `noqa`, `type: ignore`, or
  `svelte-ignore` without a concise reason and a concrete follow-up path.
- Avoid TODO/FIXME comments in committed code. Prefer creating or linking a
  tracker issue when work must be deferred.

## Commit Guard

- `scripts/code_quality_guard.py` checks staged changes for generated files,
  likely secrets, new oversized files, suppressions, broad catches, cross-skill
  imports, store-internal imports, and path-scoped deterministic audits.
- Run it manually with `python3 scripts/code_quality_guard.py` when preparing a
  risky refactor.
