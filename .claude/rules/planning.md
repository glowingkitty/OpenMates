---
description: Scope, approval and bounded debugging
globs:
---

Discover relevant source, existing tests, Specifications and prior decisions
before asking questions. A clear implementation request authorizes its routine
implementation and focused verification. Preserve prior approvals and waivers.
Ask only when expected behavior, a material risk or a scope decision remains
unresolved. Explain the evidence and preferred option; do not require a fixed
number of questions or a second understanding-confirmation round.

Use a concise inline goal and acceptance criteria for ordinary work. Use
`docs/plans/<slug>/plan.yml` for material architecture/risk or durable multi-session
work; only explicitly required checks gate completion. Engineering workflow
changes do not need a product Specification. A product Specification is needed
when defining or changing an approved product contract, not for routine repairs.

Update relevant E2E coverage for behavior fixes/features. After two unsuccessful
attempts with the same approach, reassess. If a failure is unrelated, expected
behavior is uncertain, or the solution materially expands the task, explain what
is known and ask the user before resuming that expanded work. Preserve completed
changes and evidence. Continue only independent work whose scope is clear.
Never repeatedly retry the same deterministic denial.

Keep refactors coherent: update call sites with the moved implementation. Do not
leave intermediate commits that break imports. See `.claude/rules/testing.md`
for verification and `AGENTS.md` for shared ownership and deployment rules.
