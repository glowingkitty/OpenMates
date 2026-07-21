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

New full specs declare `schema_version: 2`. Existing specs without that field
remain Schema V1 and are validated under the legacy contract until they are
actively resumed for material implementation work. Do not bulk-migrate old
specs solely to satisfy this guide.

## Risk Tiers

Choose the lightest contract that safely protects the work:

### Tier 2: Full Executable Spec

Use `docs/specs/<slug>/spec.yml` for high-risk or durable multi-session work:

- Auth, encryption, billing, privacy, teams, sharing, permissions, sync, AI
  pipeline, provider integrations, migrations, and Directus schema changes.
- New API routes, app skills, embed types, background jobs, or cron jobs when
  their contract crosses trust, persistence, or deployment boundaries.
- Work with material architecture/rollout decisions, disputed behavior, or
  multiple independent implementation sessions.

Tier 2 keeps the full approval, decision, task, handoff, and evidence ledger.

### Tier 1: Inline Contract

Use a concise issue or session task for ordinary non-trivial work, including
most multi-file and user-facing changes with clear behavior. Record only:

- Goal and explicit non-goals.
- Verifiable acceptance criteria.
- Ordered implementation slices or affected areas.
- Exact relevant checks and any genuine user decision still required.

Do not create a YAML full spec merely because a change touches several files or
has UI states. Escalate to Tier 2 only when the risk or durable coordination
needs above are present.

### Tier 0: No Spec

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
2. Perform bounded discovery before stating an understanding or asking questions:
   GitHub Issues, relevant
   Linear tasks only when appropriate, `docs/specs/`, `docs/architecture/`, user
   guides, source code, and existing tests. If the work touches a shared product
   surface with an Apple counterpart, discover the mapped Swift files and Apple
   parity docs too.
3. Ask up to five rounds of clarifying questions, one question per message. Wait
   for the user's response before asking the next question. The questions must
   be based on discovered context and focus on blocking product decisions.
4. Summarize the understood vision, scope, non-goals, verified facts, and
   unresolved decisions. Do not present an inference as a repository fact. Wait
   for user confirmation before writing the final full spec.
5. Create or update `docs/specs/<slug>/spec.yml`.
6. Run `python3 scripts/spec_validate.py docs/specs/<slug>/spec.yml`.
7. Present the product contract to the user and record product-contract approval.
8. Use `plan-from-spec` and `tasks-from-spec` to fill `implementation_plan` and
   `tasks` inside the same `spec.yml`. Record a separate technical-plan approval
   only when the plan introduces a material architecture, security, privacy,
   migration, rollout, or external-dependency decision not already covered by
   the approved product contract.
9. Write or update the tests listed in `spec.yml` before feature code. For new
   shared functionality, list REST/API evidence first, CLI evidence second,
   npm SDK and pip SDK evidence third, web Playwright evidence fourth, user confirmation fifth when web UI is
   involved, and Apple remote evidence last when the Apple app has a counterpart.
   REST/API, CLI, and SDK tests first run against the dev server; only after they
   pass should the same coverage move or wire into GitHub Actions for daily tests.
10. Run the listed red-phase tests in the same order and record evidence in
    `spec.yml`.
11. Before implementation starts, confirm required assumptions and normalize
    vague acceptance criteria such as "all tests pass" into concrete scoped
    checks. Required criteria must have `coverage_status`, `verification_scope`,
    and `verification_ids`, or an explicit user confirmation, waiver, or blocker.
12. Implement one small requirement slice at a time. Update `handoff` before a
    non-trivial action and after a verified result, failed attempt, scope change,
    or blocker so a fresh session can continue without chat context.
13. Deploy before Playwright green-phase verification because Playwright specs
    run against `app.dev.openmates.org`.
14. Run green-phase tests in REST/API → CLI → SDK → web → user confirmation → Apple order,
    record evidence in `spec.yml`, and run `python3 scripts/spec_verify.py
    docs/specs/<slug>/spec.yml`.

An active implementation spec is non-interruptible. Continue from its current
handoff until verification completes; task size, context pressure, test failure,
concurrent work, and a later-phase gate are not stop conditions. A pause requires
a structured `handoff.blocker` for the **current** task with `task_id`,
`requires_user_input: true`, `reason`, `question`, and `next_action`. Do not use
an unstructured or future-task blocker to suppress current-task implementation.

Material changes to an acceptance criterion, test assertion, contract,
assumption, or linked implementation invalidate its green evidence. Preserve the
old evidence as history, mark the affected task `needs_fix` or `in_progress`,
and record replacement evidence for the new subject revision. Never retain a
passing status merely because it was true for an earlier revision.

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

## New Functionality Phase Gates

Every new functionality spec must define the implementation and verification
ladder before implementation starts. For app skills, focus modes, embed types,
memory types, provider-backed behavior, settings-backed chat behavior, and other
shared product surfaces, this order is mandatory:

1. **REST API/WebSocket contract first:** implement the backend contract and prove
   it with a direct REST request, WebSocket probe, or focused API smoke script
   against the dev server. The spec must classify every changed endpoint as
   unauthenticated public REST API, developer API-key REST API, first-party client
   surface only, or internal-only. It must also state auth, owner/team scoping,
   rate limits, credit/budget limits, and whether client-side encrypted data or
   decrypted plaintext is handled. For endpoints that accept or return
   client-side encrypted chat, memory, file, key, sync, or share material, default
   to first-party or internal-only access unless the approved spec explains how a
   public/developer contract preserves encryption boundaries. The dev-server
   REST/API proof must pass before CLI, SDK, web, or Apple work starts.

   REST/API phase-gate evidence must hit the real dev API and WebSocket services
   with real auth/test-account state. It must verify the happy path and relevant
   unauthorized, forbidden, rate-limited, or budget-limited behavior for the
   endpoint classification. Mocked `fetch`,
   mocked SDK clients, stubbed local servers, fixture replay, direct function
   calls, and unit tests that bypass the OpenMates API/WebSocket path are
   supplemental only and do not satisfy the REST/API-first gate. If a third-party API
   call is expensive, run a low-cost real request or record a user-approved waiver
   before provider replay can stand in for that external call.
2. **OpenMates CLI second:** implement the CLI path and prove it with a CLI
   command, CLI contract test, or real CLI chat against the dev server. The
   dev-server CLI proof must pass before SDK, web, or Apple work starts. The CLI
   proof exercises shared backend/API/WebSocket behavior without browser or
   native UI state.
3. **SDK parity third:** implement and test npm SDK and pip SDK parity locally
   against the dev server for the same shared behavior when it is exposed
   programmatically. Run `python3 scripts/audit_sdk_cli_parity.py` when the CLI
   or SDK surface changes.
   Only after local REST/API, CLI, and SDK evidence is green should the same
   coverage be reproduced or wired into GitHub Actions so it runs in the daily
   test suite.
4. **Web app fourth:** implement the web app only after REST/API, CLI, and SDK parity are
   green. Run the relevant Playwright `*.spec.ts` through
   `python3 scripts/tests.py run --spec <name>.spec.ts` after deploy.
5. **User confirmation fifth:** for user-visible web UI or behavior, get the
   user's confirmation that the deployed dev web app works and looks correct.
   Automated `*.spec.ts` evidence is necessary but not sufficient for this gate.
6. **Apple app last:** start Apple parity only after REST/API, CLI, SDK, web, and required
   user-confirmation evidence are complete. Use `python3 scripts/apple_remote.py
   test-ios` when a targeted native test exists, otherwise `build-ios`. Use
   `Apple not affected` only when the spec confirms there is no native counterpart.

Do not start a later client while an earlier phase is unimplemented, untested,
or blocked unless the spec records an explicit user-approved waiver or accepted
external blocker for that phase.

Skip the REST/API-first and CLI phases only for clearly browser-only changes, such as
selectors, layout/screenshot diffs, pointer-event overlays, or Svelte-only
rendering. Skip user confirmation only for non-visual, non-user-facing work or
with an explicit user waiver. Skip Apple verification only when there is no Apple
counterpart or when `scripts/apple_remote.py` records a sanitized access/build
failure.

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

## Schema V2 Contract

Schema V2 makes the durable full spec a complete work ledger. New full specs
must include the existing scenarios, acceptance criteria, tests,
`implementation_plan`, and `tasks`, plus:

- `implementation_state.subject_commit`: the revision whose evidence is current.
- `approvals.product_contract` and `approvals.implementation_plan`: separate
  approval states, timestamps, and reasons for non-required, waived, or blocked
  approvals.
- `decisions`: durable decision, reason, status, and timestamp records.
- `attempts`: failed, rejected, blocked, planned, or successful approaches linked
  to the task they informed.
- `handoff`: current task, exact next command, expected outcome, blocker, and
  last verified revision. A blocker pauses continuation only when it is a
  structured user-input blocker for that current task.
- task `ownership`, `dependencies`, `expected_files`, verification IDs, blockers,
  and follow-up links.

For full specs, `spec.yml` is the only durable plan and task ledger. Do not
create a session task file that duplicates its scenarios, acceptance criteria,
tasks, status, or handoff. Session task files remain appropriate for inline-spec
and non-spec work.

Evidence is a claim of action and must support that claim. Recorded automated
evidence requires `command`, `run_id`, `timestamp`, and `subject_commit`.
Playwright evidence also records its live target and deployment reference.
Manual checks, skips, waivers, and blockers require a reason, actor when known,
timestamp, and next action or recheck condition where applicable.

## Spec YAML Template

```yaml
schema_version: 2
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

implementation_state:
  subject_commit: <COMMIT_SHA>

approvals:
  product_contract:
    status: approved
    approved_at: ""
  implementation_plan:
    status: not_required
    reason: Existing architecture satisfies the approved contract.

decisions:
  - id: D-1
    status: active
    decision: Reuse the existing authenticated-route dependency.
    reason: It provides the required user identity and authorization boundary.
    decided_at: ""

attempts:
  - id: ATTEMPT-1
    task_id: TASK-1
    approach: Add the API contract test before route implementation.
    outcome: planned
    recorded_at: ""

handoff:
  current_task_id: TASK-1
  next_action: Write and run the red backend contract test.
  command: python3 -m pytest backend/tests/test_teams.py
  expected_outcome: The test fails because the route does not exist yet.
  blocker: null
  last_verified_commit: <COMMIT_SHA>

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
    required: true
    status: pending # pending | satisfied | failed | waived | blocked
    coverage_status: covered # uncovered | covered | ambiguous | blocked | waived
    verification_scope: related_backend
    verification_ids:
      - T-PYTEST-001

assumptions:
  - id: A-1
    text: Existing auth dependencies can identify the current user for team APIs.
    category: auth
    required_before: implementation # implementation | task_execution | completion | never
    status: confirmed # unchecked | checking | confirmed | corrected | contradicted | blocked | waived
    evidence:
      - source: backend/core/api/app/routes/auth_routes/auth_dependencies.py
        summary: Existing dependency returns the current user for authenticated API routes.

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
        command: ""
        run_id: ""
        subject_commit: ""
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

verifications:
  - id: V-MANUAL-001
    kind: user_confirmation # automated_test | deterministic_check | manual_check | ai_evaluation | user_confirmation | artifact_review
    phase: final # red | green | final | not_applicable
    required_for_done: true
    covers:
      - AC-1
    status: pending # pending | passed | failed | passed_unexpectedly | skipped | waived | blocked
    evidence:
      status: ""
      summary: ""
      timestamp: ""

implementation_plan:
  spec_path: docs/specs/teams-v1/spec.yml
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
    - Direct REST API/WebSocket backend contract against the dev server first, with access model, auth, rate-limit, credit/budget, and encryption-boundary classification
    - Real CLI command against the dev server second, with no mocked OpenMates API/WebSocket calls
    - npm SDK and pip SDK parity locally against the dev server third when applicable
    - GitHub Actions CI/daily-test reproduction only after local REST/API, CLI, and SDK success
    - Web Playwright fourth when applicable
    - User confirmation fifth for user-visible deployed web behavior
    - Apple remote test/build last when applicable

tasks:
  - id: TASK-1
    title: Create team backend slice
    status: pending # pending | in_progress | done | blocked | needs_fix | cancelled
    phase: working_tasks
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
    verification_ids:
      - T-PYTEST-001
    dependencies: []
    ownership:
      files:
        - backend/core/api/app/routes/teams.py
        - backend/tests/test_teams.py
      shared_files: []
    blockers: []
    follow_up_tasks: []
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
Red-phase evidence may be `failed_as_expected`, `passed_unexpectedly`,
`missing_test`, `skipped_with_reason`, or `not_applicable`; required green/final
evidence must pass, be user-confirmed, waived, or be blocked by an accepted
user/external dependency. Failed required checks keep the spec active and should
create or suggest follow-up tasks linked to the failed verification and affected
acceptance criteria.

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
