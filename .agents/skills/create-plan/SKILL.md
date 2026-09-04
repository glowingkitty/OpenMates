---
name: create-plan
description: Create or update an executable Plan linked to approved Specifications before non-trivial OpenCode implementation work
user-invocable: true
argument-hint: "<feature | bug | issue id | specification path | docs/plans/<slug>/plan.yml>"
---

## Instructions

You are creating the executable implementation Plan for a non-trivial OpenMates
change. Clarify the user's vision, discover approved Specifications and existing
patterns, create one YAML Plan, and stop before implementation until the user
approves the Plan.

Read `docs/contributing/guides/spec-driven-development.md` before writing or
updating a Plan.

### Step 1: Decide Plan Size

| Risk tier | Use when | Artifact |
| --- | --- | --- |
| Tier 0 | Trivial/mechanical work | No Plan |
| Tier 1 | Ordinary non-trivial work with clear behavior | Issue or session Plan |
| Tier 2 | High-risk or durable multi-session work | `docs/plans/<slug>/plan.yml` |

Tier 2 Plans are required for auth, encryption, billing, privacy, teams,
sharing, permissions, sync, AI pipeline, provider integrations, migrations, new
API routes, app skills, embed types, background jobs, cron jobs, and Directus
schema changes.

### Step 2: Discover Context And Specifications

Before asking questions or drafting:

1. Search existing GitHub Issues by default if this is tracker work, and relevant
   Linear tasks only when appropriate.
2. Search `specifications/`, `docs/plans/`, `docs/architecture/`, user guides,
   relevant source directories, and related tests.
3. Identify the governing approved Specification bundle and record its exact
   reference and fingerprint. For a new feature or semantic behavior change, run
   `define-specification` and wait for approval before creating the Plan.
   Implementation-only work references the current approved Specification.
4. Read likely related tests so each task and verification maps to real paths.

For a Tier 2 Plan, ask up to five clarifying questions, exactly one per message,
then summarize verified facts, uncertainties, scope, non-goals, and unresolved
decisions. Wait for user confirmation before writing `plan.yml`.
Every question must include `Recommendation:` with the evidence-based preferred
answer and rationale plus `Examples:` with task-specific outcomes. If evidence
is incomplete, recommend the safest reversible default and state the uncertainty.

### Step 3: Write The Plan

For a full Plan, create or update:

```text
docs/plans/<slug>/plan.yml
```

The Plan must include:

- `schema_version`, linked Specification references and affected assertion IDs
- Goal, scope, non-goals, discovery summary, assumptions, risks, and decisions
- Numbered scenarios (`S-*`) and acceptance criteria (`AC-*`)
- Technical boundaries, data-flow examples, affected files, rollout needs, and
  documentation impact
- Small vertical-slice tasks with status, ownership, dependencies, verification
  IDs, and evidence/handoff records
- Tests with red and green phase metadata plus concrete verification commands
- The required cross-client phase order: REST API/WebSocket, CLI, npm/pip SDKs,
  CI/daily reproduction, web, deployed Playwright visual smoke, user
  confirmation, then Apple
- Endpoint access classification, auth, limits, budget/credit limits, and
  encrypted-data handling where applicable
- Required demonstration and visual-smoke records for observable product surfaces

Do not create a second nested planning stage. A Plan is the implementation
plan and its tasks are direct children of the Plan.

Run validation before presenting the Plan:

```bash
python3 scripts/plan_validate.py docs/plans/<slug>/plan.yml
```

### Step 4: Review Gate

After drafting, summarize:

```markdown
Plan: docs/plans/<slug>/plan.yml
Specifications: <approved references>
First slice: <short description>
Open questions: <none or list>
Validation: <plan_validate result>
Next: approve the Plan, then run `tasks-from-plan docs/plans/<slug>/plan.yml`
```

Do not implement code during this skill.

## Rules

- Specifications are product truth; Plans describe implementation and evidence.
- Full Plans are executable YAML only. Do not create a nested implementation-plan
  artifact inside a Plan.
- Keep Plans concise; concrete examples and checks are more valuable than prose.
- Do not commit secrets, private user data, raw logs, private emails, or
  production identifiers.
