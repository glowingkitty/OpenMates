# Plans and Specifications

Choose the lightest record that protects user intent. Trivial/mechanical changes
need no Plan. Ordinary clear changes use an inline goal and acceptance criteria.
Material architecture/risk or multi-session work uses `docs/plans/<slug>/plan.yml`.

New Plans use `schema_version: 2` and a user-authored `goal`. Other fields are
optional; only explicitly required checks gate completion. OpenMates Tasks owns
status/dependencies. Do not duplicate that ledger in a Plan. Preserve historical
plans without bulk migration. Existing approval authorizes implementation; do not
restart question/approval rounds to transcribe it. Ask when a material product or
rollout decision actually remains unresolved.

Specifications define approved reusable product behavior. Routine repairs use
existing assertions; defining or changing the product contract uses
`define-specification` and its exact review artifact. Engineering workflow changes
need no product Specification. Validate Plans with `scripts/plan_validate.py`.

Update E2E coverage for fixes/features. Product REST/WebSocket, CLI/SDK and browser
tests run in the existing isolated GitHub stack. Local unit/lint/build checks
support them. Select affected clients/checks; do not impose an unrelated fixed
cross-client ladder. `.claude/rules/testing.md` defines bounded debugging and
preserving user waivers. Proof/video production is optional unless requested or
explicitly required by accepted scope. Record actual evidence without inventing
passes or treating queued work as complete.
