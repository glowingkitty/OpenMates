---
name: add-memory-type
description: Create or update OpenMates user-facing memory/settings categories with minimal schemas, privacy review, app.yml metadata, i18n, docs, and tests
user-invocable: true
argument-hint: "<appId?> <memoryId?>"
---

## Purpose

Use this skill when the user wants to create or update an OpenMates memory type
or settings/memories category. OpenMates memories are user-facing, app-scoped
encrypted data categories that users can manage in Settings > Apps and share
with a mate only after per-conversation permission.

This is not for OpenCode memory, agent memory, browser storage, or generic notes.

## Core Product Rule: Keep Memory Schemas Minimal

Memory entries must be easy for normal users to fill out. Target **1-4
user-entered fields** per memory entry.

Rules:
- Prefer 1-2 fields when the memory is a simple preference.
- Prefer 3-4 fields only when list entries need a title plus essential context.
- Avoid 5+ user-entered fields unless the user explicitly approves the extra friction.
- Do not model every possible detail. Store the minimum useful data that helps the mate personalize future answers.
- Use `notes` as an optional multiline field only when it meaningfully replaces several niche fields.
- Do not add `added_date`; it is auto-injected by backend/frontend metadata generation.
- Do not collect sensitive fields unless the user confirms the need and the privacy boundary is explicit.

## Arguments

Parse `$ARGUMENTS` as optional hints:
- `appId` — parent OpenMates app directory, such as `travel`, `books`, `health`, or `code`
- `memoryId` — memory category id, snake_case preferred, such as `favorite_books` or `communication_style`

If either value is missing, infer it during discovery or ask during the
clarifying rounds. Do not invent a final app or ID without user confirmation.

## Workflow

Follow this structure closely. The user expects the same deliberate
plan-before-build flow as focus mode authoring: existing-state research,
clarification, internal research, external research, more clarification, draft,
feedback, finalization, then implementation.

### Step 1: Check Existing Memory Types

First inspect how memory types already exist and how the target app is
structured.

Read or search these paths as relevant:
- `docs/user-guide/apps/settings-and-memories.md`
- `backend/shared/python_schemas/app_metadata_schemas.py` (`AppMemoryFieldDefinition`)
- `backend/apps/*/app.yml` (`settings_and_memories`)
- `backend/apps/{appId}/app.yml`
- `frontend/packages/ui/src/i18n/sources/settings/app_settings_memories.yml`
- `frontend/packages/ui/scripts/generate-apps-metadata.js`
- `frontend/packages/ui/src/types/apps.ts` (`MemoryFieldMetadata`, `SchemaPropertyDefinition`)
- `frontend/packages/ui/src/components/settings/AppSettingsMemoriesCreateEntry.svelte`
- `frontend/packages/ui/src/components/settings/AppSettingsMemoriesCategory.svelte`
- `frontend/apps/web_app/tests/mention-dropdown-settings-memory.spec.ts`
- `frontend/apps/web_app/tests/cli-memories.spec.ts`

Identify whether the request is:
- creating a new memory type
- updating an existing memory type
- simplifying an over-complex schema
- adding examples/i18n only
- changing how a skill or focus mode uses existing memory data

### Step 2: Ask 3 Clarifying Rounds

Ask exactly one clear question per round and wait for the user's answer before
continuing. Stop early only if the user explicitly says to skip clarification.

Use these topics unless the repo context reveals more urgent blockers:
- Round 1: What user data should this memory help the mate remember?
- Round 2: Which app should own it, and should it be a new category or update an existing one?
- Round 3: Should this be a `single` preference or a `list` of entries, and what are the 1-4 essential fields?

If the user proposes more than 4 fields, challenge the scope before proceeding:
ask which fields are truly necessary for useful personalization and which can be
merged into optional `notes` or left out.

### Step 3: Search Internal Context

Based on the answers, search internal sources for relevant connected
information and ideas.

Check:
- similar `settings_and_memories` schemas in other apps
- related app skills or focus modes that may request this memory
- GitHub issues for related product ideas, privacy concerns, or prior decisions
- docs and tests for the affected app/domain
- settings UI behavior for the proposed field types
- whether the memory should appear in mention dropdowns or app-store examples

Use GitHub Issues by default for tracker searches. Do not create or update an
issue unless the user asks.

### Step 4: Search External Context

Search externally for ideas and best practices relevant to the requested memory
type.

Use:
- GitHub search for similar app data models, AI assistant memories, preference
  schemas, or user profile data categories
- web search for domain best practices
- official or authoritative sources when the memory touches health, finance,
  legal, safety, education, jobs, security, privacy, minors, or other high-risk topics

Keep this research practical. Extract only fields and privacy boundaries that
improve the OpenMates memory contract. Do not copy large data models; OpenMates
memory entries should stay minimal.

### Step 5: Ask 3 More Clarifying Rounds

Ask exactly one clear question per round and wait for the user's answer before
continuing.

These questions must be informed by internal and external research. Use them to
resolve:
- which proposed fields can be removed or merged to keep the schema within 1-4 fields
- sensitive fields to avoid
- required vs optional fields
- title/subtitle display behavior in settings
- example entries
- how the AI may use this memory and when it must ask for permission
- how proactive, cautious, structured, or conversational the mate should be when suggesting saved entries

### Step 6: Suggest a Draft

Present a concise draft and ask for feedback before editing product files.

The draft must include:
- display name
- parent app
- runtime memory ID
- type (`single` or `list`)
- stage (`planning`, `development`, or `production`)
- one-line description
- schema fields, explicitly marking the 1-4 user-entered fields
- required fields
- title/subtitle display fields
- example entries
- how the AI may use this memory after permission
- how the AI should suggest saving new entries
- non-goals
- safety, privacy, and data-use rules

If the draft has more than 4 user-entered fields, include a short justification
and ask the user to explicitly approve the extra complexity.

For updates, show a focused diff-style summary of what will change.

### Step 7: Ask for Feedback

Wait for the user's feedback. Do not implement before this gate unless the user
explicitly says to proceed without draft approval.

### Step 8: Finalize the Draft

Incorporate feedback and show the final version briefly. Confirm any remaining
tradeoffs, such as default-enabled behavior, field count, required fields, or sensitive data
boundaries.

### Step 9: Implement the Memory Type

Update the current OpenMates metadata and i18n sources.

Primary implementation target:
- `backend/apps/{appId}/app.yml` under `settings_and_memories:`

Usually required i18n target:
- `frontend/packages/ui/src/i18n/sources/settings/app_settings_memories.yml`

Potentially relevant docs/tests:
- `docs/user-guide/apps/settings-and-memories.md`
- app-specific docs under `docs/user-guide/apps/` or `docs/architecture/apps/`
- `frontend/apps/web_app/tests/mention-dropdown-settings-memory.spec.ts`
- `frontend/apps/web_app/tests/cli-memories.spec.ts`

Rules:
- Runtime `id` is snake_case.
- Use `settings_and_memories`, not legacy `memory_fields` or `memory`, for new work.
- Use `type: single` for one user preference object and `type: list` for repeatable entries.
- New unverified memory types should usually start as `stage: development`.
- Add `icon_image` only if an appropriate existing icon exists.
- Keep user-entered schema fields to 1-4 whenever possible.
- Mark exactly one useful `is_title: true` field for list readability when possible.
- Use `is_subtitle: true` only when it materially improves scanning.
- Prefer enum fields only when the choices are stable and user-friendly.
- Prefer `format: date`, `format: uri`, or `format: email` only when the UI and validation benefit.
- Use `multiline: true` for optional notes, not for every text field.
- Do not add `added_date`; it is auto-injected.
- Do not add sensitive identifiers, secrets, payment details, medical record numbers, government IDs, or credentials.
- For health/legal/finance/safety memories, add conservative wording in the draft and avoid encouraging diagnosis, legal advice, or financial decisions based only on saved memory.

### Step 10: Validate

Run the smallest checks that prove the change.

Usually relevant:
- `cd frontend/packages/ui && npm run build:translations` after i18n YAML edits
- `cd frontend/packages/ui && npm run generate-apps-metadata` after app metadata edits
- `cd frontend/packages/ui && npm run validate:locales` if translations changed
- targeted lint or typecheck command for changed areas when available

For user-facing memory behavior, propose the relevant E2E test path and use the
repo test runner after deploy when running Playwright:
- `python3 scripts/tests.py run --spec mention-dropdown-settings-memory.spec.ts`
- `python3 scripts/tests.py run --spec cli-memories.spec.ts`
- a new or updated app-specific memory spec if needed

Do not run Playwright locally.

## Draft Template

Use this structure for Step 6 and Step 8.

```markdown
## Memory Type Draft

Name:
App:
Memory ID:
Type: single | list
Stage:

Description:

User-entered fields (target 1-4):
1. field_name — type — required/optional — purpose

Auto-generated fields:
- added_date (injected automatically; do not define manually)

Title/subtitle display:

Example entries:
- ...

How the AI may use it after permission:

How the AI may suggest saving it:

Non-goals:

Safety and privacy:

Open questions:
```

## Implementation Checklist

Before finishing, verify:
- memory ID is snake_case
- app uses `settings_and_memories:`
- schema has 1-4 user-entered fields unless explicitly approved otherwise
- schema has no manual `added_date`
- required fields are genuinely necessary
- at least one field is marked `is_title: true` for list entries when possible
- any `is_subtitle: true` field is actually useful for scanning
- examples match the schema and avoid private or sensitive values
- i18n keys exist in `settings/app_settings_memories.yml`
- generated translations and app metadata were rebuilt if source files changed
- docs/tests were updated or explicitly deferred

## When to Escalate to a Full Spec

Use `specify` before implementation if the memory type changes persistence,
permissions, encryption, sharing, Directus schema, sync behavior, AI permission
dialogs, new API routes, or app skill behavior. Pure metadata/i18n additions can
usually follow this skill without a full spec.
