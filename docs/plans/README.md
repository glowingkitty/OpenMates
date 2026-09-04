# Specs

This directory contains durable, committed implementation specs for non-trivial
OpenMates work. Approved bundles under `contracts/` are the permanent behavior
source of truth; specs define the changing intent, scenarios, acceptance
criteria, concrete tests, tasks, attempts, handoff, and evidence used to satisfy
those contracts.

Use a full spec folder when work is complex, risky, user-facing, or likely to
span more than one session. New full specs use a single executable YAML source
of truth:

```text
docs/plans/<slug>/
└── spec.yml
```

Older spec folders from the previous workflow should be migrated into
`spec.yml` when they are actively resumed. Do not create separate Markdown spec,
plan, or task files for new specs.

Contract-aware specs use Schema V3 and retain the complete Schema V2 ledger plus
`specification_refs`, contract/assertion impact, and documentation impact. Complete,
deployed or released V3 specs become archive-eligible after a 30-day cooling
period. `python3 scripts/specifications.py archive-specs` moves them into a year-based
archive; it never deletes specs. Archived specs remain searchable but are not
loaded by default.

Do not store secrets, private user data, raw logs, private emails, or production
identifiers here. Use placeholders such as `<USER_EMAIL>`, `<CHAT_ID>`, and
`<TEAM_ID>`.

See `docs/contributing/guides/spec-driven-development.md` for sizing rules,
templates, and the OpenCode workflow.
