# Specs

This directory contains durable, committed specs for non-trivial OpenMates work.
Specs are source-of-truth artifacts for OpenCode sessions: they define intent,
examples, acceptance criteria, contracts, test coverage, and implementation
tasks.

Use a full spec folder when work is complex, risky, user-facing, or likely to
span more than one session:

```text
docs/specs/<slug>/
├── spec.md
├── plan.md
└── tasks.md
```

Do not store secrets, private user data, raw logs, private emails, or production
identifiers here. Use placeholders such as `<USER_EMAIL>`, `<CHAT_ID>`, and
`<TEAM_ID>`.

See `docs/contributing/guides/spec-driven-development.md` for sizing rules,
templates, and the OpenCode workflow.
