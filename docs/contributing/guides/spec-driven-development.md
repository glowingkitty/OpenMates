---
status: active
last_verified: 2026-06-06
---

# Spec-Driven Development

OpenMates uses executable spec-driven development for non-trivial work. The goal
is to protect product intent before OpenCode changes production code: clarify the
user's vision, write a machine-checkable product contract, create tests first,
then implement small verified slices.

Full specs use a single YAML source of truth:

```text
docs/specs/<slug>/spec.yml
```

Do not maintain separate Markdown spec, plan, or task files for new full specs.
If a readable document is needed, generate it from `spec.yml` instead of
duplicating content by hand.

## When Specs Are Required

Automatically use the spec workflow before implementation when work is complex,
risky, user-facing, or likely to be misunderstood:

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
- Refactors where behavior must stay unchanged and the spec is mostly invariants
  plus regression tests.
- Existing issues that already include clear examples and acceptance criteria.

Skip specs for trivial or mechanical work:

- Typo or docs-only edits.
- Pure translation updates.
- One-line config changes.
- Mechanical renames with no behavior change.
- Generated files rebuilt from an existing source change.
- Test-only maintenance where expected behavior is already encoded in the test.
- Small CSS polish that does not change flow, accessibility, responsive behavior,
  or user-visible state.

## Workflow

For full specs:

1. Detect the user's implementation intent and auto-select `specify`.
2. Discover existing context before asking questions: GitHub Issues, relevant
   Linear tasks only when appropriate, `docs/specs/`, `docs/architecture/`, user
   guides, source code, and existing tests. If the work touches a shared product
   surface with an Apple counterpart, discover the mapped Swift files and Apple
   parity docs too.
3. Ask up to five rounds of clarifying questions, one question per message. Wait
   for the user's response before asking the next question. The questions must
   be based on discovered context and focus on blocking product decisions.
4. Summarize the understood vision, scope, non-goals, and unresolved decisions.
   Wait for user confirmation before writing the final full spec.
5. Create or update `docs/specs/<slug>/spec.yml`.
6. Run `python3 scripts/spec_validate.py docs/specs/<slug>/spec.yml`.
7. Present the spec to the user and wait for approval.
8. Use `plan-from-spec` and `tasks-from-spec` to fill `implementation_plan` and
   `tasks` inside the same `spec.yml`.
9. Write or update the tests listed in `spec.yml` before feature code. For new
   functionality, list CLI evidence first, web Playwright evidence second, and
   Apple remote evidence third when the Apple app has a counterpart.
10. Run the listed red-phase tests in the same order and record evidence in
    `spec.yml`.
11. Implement one small requirement slice at a time.
12. Deploy before Playwright green-phase verification because Playwright specs
    run against `app.dev.openmates.org`.
13. Run green-phase tests in CLI → web → Apple order, record evidence in
    `spec.yml`, and run `python3 scripts/spec_verify.py
    docs/specs/<slug>/spec.yml`.

Implementation must not begin before the user approves the full spec unless the
user explicitly instructs OpenCode to skip the spec gate.

## Apple Impact And Parity

For specs that change chat, sync, auth, settings, embeds, billing, shared UI,
or any other surface that exists in the Apple app, include an `apple_impact`
section in `spec.yml` before approval. If there is no Apple counterpart, state
that explicitly so future agents do not have to rediscover it.

The section should list affected Swift files or `none`, parity expectations,
required native tests or manual Mac verification, and any intentional native
differences. When runtime verification is required, prefer XcodeBuildMCP on a
Mac; if the active session runs on Linux, use the redacted remote wrapper in
`scripts/apple_remote.py` and keep private connection details out of the spec.
At minimum, record `python3 scripts/apple_remote.py status` plus `build-ios` or
`test-ios` evidence, or a sanitized failure class such as `ssh_failed`,
`project_not_found`, or `xcode_build_failed`.

## New Functionality Verification Order

Every new functionality spec must define the verification ladder before
implementation starts:

1. **OpenMates CLI first:** a CLI command or CLI contract test that exercises the
   shared backend/API/WebSocket behavior without browser or native UI state.
2. **Web app second:** a Playwright `*.spec.ts` run through
   `python3 scripts/tests.py run --spec <name>.spec.ts` after the CLI proof is
   green.
3. **Apple app third:** `python3 scripts/apple_remote.py test-ios` when a
   targeted native test exists, otherwise `python3 scripts/apple_remote.py
   build-ios`, after CLI and web evidence are green. Use `Apple not affected`
   only when the spec confirms there is no native counterpart.

Skip the CLI-first requirement only for clearly browser-only changes, such as
selectors, layout/screenshot diffs, pointer-event overlays, or Svelte-only
rendering. Skip Apple verification only when there is no Apple counterpart or
when `scripts/apple_remote.py` records a sanitized access/build failure.

## Feature Availability Metadata

New app metadata must not use `stage`. Implemented apps, skills, embeds, focus
modes, memory fields, and platform sections are enabled by default. Only add
`default_enabled: false` when a feature intentionally ships off by default, and
state the disabled behavior in the spec. Admin overrides use stable feature IDs
such as `app:videos`, `skill:web:search`, `embed:code:application`, and
`platform:projects`.

## Playwright Red And Green Phases

Playwright specs always test the live dev app, not undeployed local code.

- Red phase: run the new or extended `*.spec.ts` against the currently deployed
  dev app before the implementation is deployed. It should fail for the expected
  reason.
- Green phase: deploy the implementation to dev, wait until Vercel is Ready,
  then run the same spec against `app.dev.openmates.org`. It must pass before the
  spec can be marked complete.

Backend and unit tests can usually complete both red and green phases before
deploy. Playwright green evidence is always after deploy.

## Spec YAML Template

```yaml
id: teams-v1
title: Teams V1
status: draft # draft | clarifying | approved | implementing | verified

goal: >
  Let users create teams, invite members, and manage team access without exposing
  personal encrypted chat content.

scope:
  in:
    - Team creation by logged-in users
    - Email invitations for v1
    - Owner, admin, and member roles
  out:
    - Team-owned encrypted chats
    - Enterprise SSO

context_discovery:
  github_issues:
    - "#123: Existing public issue or none"
  docs:
    - docs/architecture/example.md
  code_patterns:
    - backend/core/api/app/routes/example.py
  tests:
    - frontend/apps/web_app/tests/settings.spec.ts

apple_impact:
  affected_files:
    - none
  parity_expectations:
    - No Apple counterpart for this example team settings flow yet.
  verification:
    - Not required for this example.
  intentional_native_differences:
    - none

clarification:
  rounds:
    - question: Should teams own chats in v1, or only members and billing?
      answer: Teams v1 should not own chats.
  vision_summary: >
    Teams v1 manages membership and roles. Team admins cannot read member chat
    content or personal chat metadata beyond usage totals explicitly approved in
    the spec.
  approved_by_user: false

scenarios:
  - id: S-1
    title: Owner creates a team
    given:
      - Alice is logged in
    when:
      - Alice creates a team named Acme
    then:
      - Alice becomes the team owner
      - Acme appears in team settings
      - Other users cannot see Acme

acceptance_criteria:
  - id: AC-1
    scenario: S-1
    text: A logged-in user can create a team and becomes its owner.

contracts:
  api:
    - route: POST /v1/teams
      request: "{ name: string }"
      response: "{ id: string, name: string, role: owner }"
      errors:
        - 401 when unauthenticated
  data:
    - Team records are owned by a creator user ID.
  ui_states:
    - Loading, success, validation error, unauthorized.
  privacy_security:
    - Team admins cannot read personal encrypted chat content.

tests:
  - id: T-PYTEST-001
    type: pytest
    file: backend/tests/test_teams.py
    command: python3 -m pytest backend/tests/test_teams.py
    covers:
      - AC-1
    assertions:
      - unauthenticated create returns 401
      - authenticated create stores owner membership
    red_phase:
      required: true
      expected: fail
      evidence:
        status: failed_as_expected
        run_id: ""
        timestamp: ""
    green_phase:
      required: true
      expected: pass
      evidence:
        status: ""
        run_id: ""
        timestamp: ""

  - id: T-E2E-001
    type: playwright
    file: frontend/apps/web_app/tests/teams-settings.spec.ts
    command: python3 scripts/tests.py run --spec teams-settings.spec.ts
    target: app.dev.openmates.org
    covers:
      - AC-1
    assertions:
      - teams settings entry is visible
      - create-team form creates a visible team row
    red_phase:
      required: true
      expected: fail
      evidence:
        status: ""
        run_id: ""
        timestamp: ""
    green_phase:
      required: true
      expected: pass_after_deploy
      evidence:
        status: ""
        run_id: ""
        timestamp: ""

implementation_plan:
  existing_patterns:
    - backend/core/api/app/routes/example.py
  architecture: >
    Add a teams API and settings UI using existing auth, permissions, and
    canonical settings components.
  data_flow:
    - User submits create-team form.
    - API validates auth and creates team plus owner membership.
    - UI refreshes team list.
  affected_files:
    - path: backend/core/api/app/routes/teams.py
      reason: Team API routes
  verification_strategy:
    - python3 scripts/spec_validate.py docs/specs/teams-v1/spec.yml
    - python3 scripts/spec_verify.py docs/specs/teams-v1/spec.yml
  verification_order:
    - CLI or backend contract first
    - Web Playwright second when applicable
    - Apple remote test/build third when applicable

tasks:
  - id: TASK-1
    title: Create team backend slice
    covers:
      scenarios:
        - S-1
      acceptance_criteria:
        - AC-1
    expected_files:
      - backend/core/api/app/routes/teams.py
      - backend/tests/test_teams.py
    verification:
      - T-PYTEST-001
    independently_deployable: true
```

## Scripts

Validate structure and references:

```bash
python3 scripts/spec_validate.py docs/specs/<slug>/spec.yml
```

Verify evidence before completion:

```bash
python3 scripts/spec_verify.py docs/specs/<slug>/spec.yml --phase red
python3 scripts/spec_verify.py docs/specs/<slug>/spec.yml --phase green
python3 scripts/spec_verify.py docs/specs/<slug>/spec.yml
```

`spec_validate.py` fails when acceptance criteria lack test coverage, scenario
or test IDs are malformed, Playwright tests do not target `app.dev.openmates.org`,
or Playwright green phase is not `pass_after_deploy`.

`spec_verify.py` fails when required red or green phase evidence is missing.

## Subagents And Separate Sessions

Use subagents inside the spec workflow for bounded work:

- Spec critic: review `spec.yml` for ambiguity, untestable requirements,
  missing edge cases, and privacy/security gaps.
- Test author: write tests only, with production source edits forbidden.
- Red-phase investigator: run or inspect failing tests and confirm they fail for
  the expected reason.
- Implementation agent: implement one assigned task or requirement slice only.
- Code reviewer: review the diff against `spec.yml`.

Use separate OpenCode sessions only for independent work with non-overlapping
file ownership. Ask the user before spawning separate sessions. Default spawned
sessions are planning/read-only unless the user explicitly approves execute mode.

## Commit Policy

Commit durable full specs under `docs/specs/<slug>/spec.yml` when they describe
features, risky behavior, permissions, privacy, APIs, data models, or work that
future agents need to understand.

Do not commit private user data, raw logs, credentials, private emails, secrets,
or production identifiers. Use placeholders such as `<USER_EMAIL>`, `<TEAM_ID>`,
and `<CHAT_ID>`.
