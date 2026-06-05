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
  imports, and store-internal imports.
- Run it manually with `python3 scripts/code_quality_guard.py` when preparing a
  risky refactor.
