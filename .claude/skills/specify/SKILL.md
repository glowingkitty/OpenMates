---
name: specify
description: Create or update an executable YAML spec before non-trivial OpenCode implementation work; auto-use for complex features, permissions, privacy, APIs, sync, auth, teams, providers, migrations, and multi-system changes
user-invocable: true
argument-hint: "<feature | bug | issue id | docs/specs/<slug>/spec.yml>"
---

## Instructions

You are creating the executable product contract for a non-trivial OpenMates
change. This is an OpenCode-first workflow: clarify the user's vision, produce a
single YAML spec that future OpenCode sessions can read, implement, verify, and
maintain, and stop before implementation until the user approves the spec.

Read `docs/contributing/guides/spec-driven-development.md` before writing or
updating a spec.

### Step 1: Decide Spec Size

Classify the task before creating files:

| Risk tier | Use when | Artifact |
| --- | --- | --- |
| Tier 0 | Trivial/mechanical work | No spec |
| Tier 1 | Ordinary non-trivial work with clear behavior | Issue or session contract |
| Tier 2 | High-risk or durable multi-session work | `docs/specs/<slug>/spec.yml` |

Tier 2 full specs are required for auth, encryption, billing, privacy, teams, sharing,
permissions, sync, AI pipeline, provider integrations, migrations, new API
routes, app skills, embed types, background jobs, cron jobs, and Directus schema
changes.

Use Tier 1 for most multi-file and user-facing work when goal, acceptance
criteria, test path, and implementation order are already clear. Multi-file
scope alone is not a reason to create a full YAML ledger.

If a full spec is unnecessary, explain why and produce the inline spec in the
current response or session task instead of creating files.

### Step 2: Gather Existing Context

Before asking questions or drafting:

1. Search existing GitHub Issues by default if this is tracker work.
2. Search relevant Linear tasks only when the work is Linear-only or a Linear ID
   was explicitly provided.
3. Search `docs/specs/`, `docs/architecture/`, user guides, and relevant source
   directories for prior decisions and patterns.
4. Read likely related tests so scenarios map to real verification paths.

For sensitive/private or app-recorded work, keep private details out of git and
write only sanitized product behavior.

### Step 3: Clarify The User's Vision

Ask up to five clarifying questions before writing a full spec. Ask exactly one
question per message, then wait for the user's response before deciding whether
another question is needed. Questions must be based on discovered context and
focus on decisions that block a useful product contract. Prefer concrete example
questions:

- "Can you give one example of the user flow that must work?"
- "What should happen in the failure or unauthorized case?"
- "What is explicitly out of scope for this first slice?"

After the questions, summarize verified facts, uncertainties, the user's vision,
scope, non-goals, and unresolved decisions in 2-3 sentences. Wait for user
confirmation before writing a full `spec.yml`. Do not present unverified
inferences as repository facts.

If enough context exists for a small inline spec, do not force the full five
questions.

### Step 4: Write The Spec

For a full spec, create or update:

```text
docs/specs/<slug>/spec.yml
```

Use the template from `docs/contributing/guides/spec-driven-development.md`.
Every full spec must include:

- `schema_version: 2`
- Goal
- Scope and non-goals
- Context discovery and clarification summary
- Numbered scenarios (`S-1`, `S-2`, ...)
- Numbered acceptance criteria (`AC-1`, `AC-2`, ...)
- Acceptance criteria coverage metadata when the work is implementation-bound:
  `required`, `status`, `coverage_status`, `verification_scope`, and
  `verification_ids`
- Required assumptions when implementation depends on facts that still need to be
  confirmed; each assumption needs `status`, `required_before`, and evidence or a
  blocker/waiver path
- API/data/UI/privacy contracts as applicable
- Tests with assertions, red phase, and green phase metadata
- Optional top-level `verifications` records for checks that need Plan-like
  status, evidence, blockers, waivers, or user-confirmation tracking beyond a
  simple test entry
- For shared product surfaces, explicit phase gates in this order: CLI
  implementation/testing against the dev server, GitHub Actions daily-test wiring
  after dev CLI success, npm SDK and pip SDK parity/testing, web
  implementation/testing, user confirmation of deployed dev web behavior and
  visual quality, then Apple parity/testing
- The CLI gate must use real CLI commands against the real dev API/WebSocket path
  with real auth/test-account state. Mocked OpenMates API calls, mocked SDK
  clients, stubbed servers, direct function calls, and fixture replay are
  supplemental only and do not satisfy the phase gate.
- Implementation plan and tasks placeholders or initial entries
- `implementation_state`, `approvals`, `decisions`, `attempts`, and `handoff`
- Risks, open questions, and privacy/security requirements

Scenarios must use concrete examples. Avoid abstract placeholders except for
private values such as `<USER_EMAIL>` or `<CHAT_ID>`.

Treat vague criteria as incomplete plan records. If an acceptance criterion says
"all tests pass", "no regressions", "everything works", or "fully verified",
set `coverage_status: ambiguous` and ask the user or infer concrete scoped
checks before implementation. Do not mark required criteria satisfied until they
are covered by verification_ids, user confirmation, a waiver, or an accepted
blocker.

For app skills, focus modes, embeds, memory types, provider-backed behavior, or
other cross-client features, do not write a spec that starts with web or Apple
implementation unless the earlier CLI/SDK phases are explicitly waived or
externally blocked. `*.spec.ts` evidence is not a substitute for user
confirmation before Apple parity.

Schema V2 is the full durable work ledger. Automated evidence records command,
run ID, timestamp, and subject commit. A manual check, skip, waiver, or blocker
records its reason, actor when known, and next action. Do not create a separate
task file that duplicates a full spec.

Run validation before presenting the spec:

```bash
python3 scripts/spec_validate.py docs/specs/<slug>/spec.yml
```

### Step 5: Review Gate

After drafting, summarize:

```markdown
Spec: docs/specs/<slug>/spec.yml
Size: full | inline | none
Why this size: <one sentence>
Key scenarios: S-1, S-2, ...
Open questions: <none or list>
Validation: <spec_validate result>
Next: approve the product contract, then run `plan-from-spec docs/specs/<slug>/spec.yml`
```

Do not implement code during this skill.

## Rules

- Specs are product contracts, not implementation essays.
- Full specs are executable YAML only. Do not create separate Markdown spec,
  plan, or task files for new specs.
- Keep specs concise; examples are more valuable than long prose.
- Commit durable full specs to git.
- Do not commit secrets, private user data, raw logs, private emails, or
  production identifiers.
- Use placeholders for sensitive values.
- If the spec would take longer than the change and adds no decision clarity,
  it is overkill; use inline or no spec.
