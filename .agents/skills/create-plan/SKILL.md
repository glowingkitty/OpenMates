---
name: create-plan
description: Record a concise durable Plan for material architecture, risk or multi-session work.
user-invocable: true
---

Use an inline goal and acceptance criteria for ordinary clear changes. Use
`docs/plans/<slug>/plan.yml` for material architecture/risk or durable multi-session
work. Read `docs/contributing/guides/spec-driven-development.md` when a full Plan
is needed. Discover relevant source, existing tests and approved decisions first.

A Plan requires `schema_version: 2` and the user-authored `goal`; add only useful
scope, checks, decisions and evidence. Only explicitly required checks gate
completion. OpenMates Tasks remains the status/dependency authority; do not
maintain a second task ledger. Engineering workflows need no product Specification.
Use `define-specification` only when defining/changing an approved product contract.

Existing explicit approval authorizes implementation. Do not restart question or
approval rounds just to transcribe a reviewed design. Ask for a material unresolved
decision and stop only its dependent work. Run `scripts/plan_validate.py <plan>`.
Update relevant E2E coverage for behavior changes and use isolated GitHub CI.
Apply `.claude/rules/testing.md` for bounded debugging and user execution waivers.
