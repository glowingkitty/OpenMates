---
paths:
  - "docs/plans/**"
  - "specifications/**"
---
# Planning

- Discover source, tests, Specifications and prior decisions before asking.
  A clear implementation request authorizes routine implementation and focused
  verification. Ask only for unresolved behavior, material risk or scope.
- Durable `docs/plans/<slug>/plan.yml` only for material architecture/risk or
  multi-session work; only explicitly required checks gate completion.
  Validate with `scripts/plan_validate.py <plan>`.
- Specifications only when defining/changing an approved product contract;
  engineering workflow changes need none.
- Keep refactors coherent: move call sites with the implementation.
