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

Older spec folders may still contain `spec.md`, `plan.md`, and `tasks.md` from
the previous workflow. Do not create those files for new specs; migrate legacy
specs only when they are actively resumed.

Do not store secrets, private user data, raw logs, private emails, or production
identifiers here. Use placeholders such as `<USER_EMAIL>`, `<CHAT_ID>`, and
`<TEAM_ID>`.

See `docs/contributing/guides/spec-driven-development.md` for sizing rules,
templates, and the OpenCode workflow.
