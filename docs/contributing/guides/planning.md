# Planning

Use a short task checklist for a clear fix. Use a durable YAML Plan for architecture
changes, material risk, or work spanning tasks. A Plan records the goal, affected
surfaces, intended changes, verification and unresolved decisions. Keep optional
metadata optional; approval already given in the conversation remains valid.

Create Plans under `docs/plans/<slug>/plan.yml` and use the existing validator:
`python3 scripts/plan_validate.py <path>`. A minimal Plan needs `id`, `title`, `status` and `goal`; use `profile: strict` when the accepted scope
needs the full product-contract workflow. OpenMates Tasks owns execution status; do not also
create `.claude/tasks` YAML records.

Specifications define product intent. Update them when that intent changes;
engineering-only tooling cleanup does not require inventing a product contract.
Read `spec-driven-development.md` for the product-contract workflow.

For behavior fixes/features, plan relevant E2E assertions and focused local checks.
Run full app tests through isolated GitHub CI. After two unsuccessful attempts on
the same blocker, reassess; ask before unrelated or uncertain repair work. Video
production is only a requirement when included in the accepted deliverable.
