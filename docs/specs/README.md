# Specs

This directory contains durable, committed specs for non-trivial OpenMates work.
Specs are source-of-truth artifacts for OpenCode sessions: they define intent,
examples, acceptance criteria, contracts, test coverage, and implementation
tasks.

Use a full spec folder when work is complex, risky, user-facing, or likely to
span more than one session. New full specs use a single executable YAML source
of truth:

```text
docs/specs/<slug>/
└── spec.yml
```

Older spec folders from the previous workflow should be migrated into
`spec.yml` when they are actively resumed. Do not create separate Markdown spec,
plan, or task files for new specs.

Do not store secrets, private user data, raw logs, private emails, or production
identifiers here. Use placeholders such as `<USER_EMAIL>`, `<CHAT_ID>`, and
`<TEAM_ID>`.

See `docs/contributing/guides/spec-driven-development.md` for sizing rules,
templates, and the OpenCode workflow.
