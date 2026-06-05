---
name: specify
description: Create or update a lightweight spec-driven development artifact before non-trivial OpenCode implementation work
user-invocable: true
argument-hint: "<feature | bug | issue id | docs/specs/<slug>/spec.md>"
---

## Instructions

You are creating the product contract for a non-trivial OpenMates change. This
is an OpenCode-first workflow: produce clear specs that future OpenCode sessions
can read, implement, verify, and maintain.

Read `docs/contributing/guides/spec-driven-development.md` before writing or
updating a spec.

### Step 1: Decide Spec Size

Classify the task before creating files:

| Level | Use when | Artifact |
| --- | --- | --- |
| No spec | Trivial/mechanical work | Session notes only |
| Inline spec | Small behavior change | Issue or session brief |
| Full spec | Complex, risky, multi-session work | `docs/specs/<slug>/spec.md` |

Full specs are required for auth, encryption, billing, privacy, teams, sharing,
permissions, sync, AI pipeline, provider integrations, migrations, new API
routes, app skills, embed types, background jobs, cron jobs, and Directus schema
changes.

If a full spec is unnecessary, explain why and produce the inline spec in the
current response or session task instead of creating files.

### Step 2: Gather Existing Context

Before drafting:

1. Search existing GitHub Issues by default if this is tracker work.
2. Search `docs/specs/`, `docs/architecture/`, and relevant source directories
   for prior decisions and patterns.
3. Read likely related tests so scenarios map to real verification paths.

For sensitive/private or app-recorded work, keep private details out of git and
write only sanitized product behavior.

### Step 3: Ask Only Blocking Questions

Ask at most three clarifying questions, one at a time, only for decisions that
block a useful spec. Prefer concrete example questions:

- "Can you give one example of the user flow that must work?"
- "What should happen in the failure or unauthorized case?"
- "What is explicitly out of scope for this first slice?"

If enough context exists, do not ask. Draft the spec.

### Step 4: Write The Spec

For a full spec, create or update:

```text
docs/specs/<slug>/spec.md
```

Use the template from `docs/contributing/guides/spec-driven-development.md`.
Every full spec must include:

- Goal
- Scope and non-goals
- Numbered scenarios (`S-1`, `S-2`, ...)
- Numbered acceptance criteria (`AC-1`, `AC-2`, ...)
- API/data/UI/privacy contracts as applicable
- Test matrix
- Existing patterns to reuse
- Risks and open questions

Scenarios must use concrete examples. Avoid abstract placeholders except for
private values such as `<USER_EMAIL>` or `<CHAT_ID>`.

### Step 5: Review Gate

After drafting, summarize:

```markdown
Spec: docs/specs/<slug>/spec.md
Size: full | inline | none
Why this size: <one sentence>
Key scenarios: S-1, S-2, ...
Open questions: <none or list>
Next: run `plan-from-spec docs/specs/<slug>/spec.md`
```

Do not implement code during this skill.

## Rules

- Specs are product contracts, not implementation essays.
- Keep specs concise; examples are more valuable than long prose.
- Commit durable full specs to git.
- Do not commit secrets, private user data, raw logs, private emails, or
  production identifiers.
- Use placeholders for sensitive values.
- If the spec would take longer than the change and adds no decision clarity,
  it is overkill; use inline or no spec.
