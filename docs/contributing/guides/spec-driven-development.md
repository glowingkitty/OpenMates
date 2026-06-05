---
status: active
last_verified: 2026-06-05
---

# Spec-Driven Development

OpenMates uses lightweight spec-driven development for non-trivial work. The
goal is not to create paperwork. The goal is to make intent, examples, tests,
and implementation traceable before OpenCode changes production code.

Specs are product contracts. Commit durable specs to git when they describe
features, risky behavior, permissions, privacy, APIs, data models, or work that
future agents need to understand.

## When Specs Are Required

Create a full spec for work where misunderstanding is more expensive than
writing the spec:

- New user-facing features with multiple states or paths.
- Multi-file changes across frontend, backend, data, docs, or tests.
- Auth, encryption, billing, privacy, teams, sharing, permissions, sync, AI
  pipeline, provider integrations, or migrations.
- New API routes, app skills, embed types, background jobs, cron jobs, or
  Directus schema changes.
- Features where the test plan is not obvious within two minutes.
- Bugs where expected behavior is disputed or needs product clarification.
- Tasks likely to span more than one OpenCode session.

Use an inline spec for smaller behavior changes:

- Small UI behavior changes with one happy path and one obvious assertion.
- Simple backend fixes with clear input and output.
- Refactors where behavior must stay unchanged and the spec is mostly
  invariants plus regression tests.
- Existing issues that already include clear examples and acceptance criteria.

Skip specs for trivial or mechanical work:

- Typo or docs-only edits.
- Pure translation updates.
- One-line config changes.
- Mechanical renames with no behavior change.
- Generated files rebuilt from an existing source change.
- Test-only maintenance where expected behavior is already encoded in the test.
- Small CSS polish that does not change flow, accessibility, responsive
  behavior, or user-visible state.

Rule of thumb: if writing the spec would take longer than the change itself and
does not uncover a decision, the spec is overkill.

## Spec Size Levels

| Level | When | Artifact |
| --- | --- | --- |
| No spec | Trivial or mechanical work | Session notes only |
| Inline spec | Small behavior-affecting work | Issue or session brief |
| Full spec | Complex, risky, or multi-session work | `docs/specs/<slug>/` |

## Full Spec Folder

Use this structure for full specs:

```text
docs/specs/<slug>/
├── spec.md
├── plan.md
└── tasks.md
```

`spec.md` captures the product contract: goal, scope, scenarios, acceptance
criteria, contracts, risks, and test matrix.

`plan.md` captures the technical approach: existing patterns, affected files,
data flow, contracts, migrations, observability, and verification strategy.

`tasks.md` breaks the plan into small, reviewable implementation slices. Each
task must reference scenario IDs and acceptance criteria.

## Spec Template

```markdown
# <Feature Or Bug Title>

## Goal
<What user-visible outcome changes and why.>

## Scope
In:
- <what this work includes>

Out:
- <related work intentionally not included>

## Scenarios
### S-1: <happy path>
Given <initial state>
When <user or system action>
Then <observable result>

### S-2: <error or boundary path>
Given <initial state>
When <user or system action>
Then <observable result>

## Acceptance Criteria
- [ ] AC-1: <specific, falsifiable outcome>
- [ ] AC-2: <specific, falsifiable outcome>

## Contracts
API:
- <routes, request/response shape, permissions, errors>

Data:
- <new or changed records, ownership, migration/backfill needs>

UI states:
- <loading, empty, success, error, disabled, responsive states>

Privacy/security:
- <data visibility, encryption, audit, retention, provider implications>

## Test Matrix
| Scenario | Test Type | File | Status |
| --- | --- | --- | --- |
| S-1 | Playwright | `TBD` | planned |
| S-2 | Pytest/unit | `TBD` | planned |

## Implementation Notes
Existing patterns to reuse:
- <files, components, services, docs>

Likely files touched:
- `<path>` — <why>

Risks:
- <risk and mitigation>
```

## Plan Template

```markdown
# Plan: <Title>

Spec: `docs/specs/<slug>/spec.md`

## Existing Patterns
- `<path>` — <pattern to reuse>

## Architecture
<How the implementation fits current frontend/backend/data boundaries.>

## Data Flow
1. <trigger>
2. <frontend/API/backend/storage/event step>
3. <observable result>

## Affected Files
- `<path>` — <change>

## Verification Strategy
- <test command or spec to run>
- <manual verification only if automation is not practical>

## Open Questions
- <question or none>
```

## Tasks Template

```markdown
# Tasks: <Title>

Spec: `docs/specs/<slug>/spec.md`
Plan: `docs/specs/<slug>/plan.md`

- [ ] T-1: <small vertical slice>
  Covers: S-1, AC-1
  Verify: `<test command or planned test file>`

- [ ] T-2: <next slice>
  Covers: S-2, AC-2
  Verify: `<test command or planned test file>`
```

## OpenCode Workflow

For full specs:

1. Run `specify` to create or update `spec.md`.
2. Review the spec with the user before code changes.
3. Run `plan-from-spec` to create `plan.md`.
4. Run `tasks-from-spec` to create `tasks.md`.
5. Implement one task or vertical slice at a time.
6. Run `verify-spec` before deploy.
7. Include spec and test evidence in the deploy summary.

For inline specs, keep the same shape but write it directly in the issue,
session task, or response: scenarios, acceptance criteria, and test evidence.

## Commit Policy

Commit durable specs to git. Do not commit scratch notes or private details.

Commit:

- Full feature and risk specs under `docs/specs/<slug>/`.
- Plans and tasks that explain implemented work or future maintenance.
- Sanitized specs for sensitive areas when they describe public product
  behavior without private user data.

Do not commit:

- Private user data, raw logs, credentials, private emails, or secrets.
- Temporary planning scratch files.
- Specs that only repeat an already-closed trivial change.

Use placeholders for sensitive examples, such as `<USER_EMAIL>` and
`<TEAM_ID>`.

## Example: Teams Functionality

Teams requires a full spec because it touches permissions, identity, privacy,
billing/limits, UI states, backend routes, data models, and likely migrations.

Example scenario slice:

```markdown
### S-1: Owner creates a team
Given Alice is logged in
When she creates a team named "Acme"
Then she becomes the team owner
And the team appears in her settings
And no other user can see the team

### S-2: Owner invites a member
Given Alice owns team "Acme"
When she invites `<USER_EMAIL>`
Then an invitation is created with pending status
And the invited user has no team access before accepting

### S-3: Non-admin cannot invite members
Given Bob is a team member but not an admin
When Bob tries to invite another user
Then the API returns 403
And no invite is created

### S-4: Team usage does not expose personal chat content
Given Bob sends a personal encrypted chat message
When team usage accounting runs
Then usage totals may update
But team admins cannot read Bob's personal chat content
```

Example implementation tasks:

```markdown
- [ ] T-1: Add team and membership schema plus backend create-team service.
  Covers: S-1, AC-1
  Verify: `backend/tests/test_team_permissions.py`

- [ ] T-2: Add invite create/accept/decline API with permission checks.
  Covers: S-2, S-3, AC-2, AC-3
  Verify: `backend/tests/test_team_invites.py`

- [ ] T-3: Add settings UI using canonical settings elements.
  Covers: S-1, S-2, AC-4
  Verify: `frontend/apps/web_app/tests/teams-settings.spec.ts`

- [ ] T-4: Add team usage accounting without plaintext content access.
  Covers: S-4, AC-5
  Verify: `backend/tests/test_team_usage_privacy.py`
```

The first coding slice should be create-team only, not all of teams. Keep every
slice independently reviewable and testable.
