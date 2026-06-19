---
name: openmates:add-focus-mode
description: Create or update OpenMates user-facing focus modes using the existing SKILL.md, app.yml, i18n, docs, and test patterns
user-invocable: true
argument-hint: "<appId?> <focusId?>"
---

## Purpose

Use this skill when the user wants to create or update an OpenMates focus mode.
OpenMates focus modes are user-facing chat modes that temporarily change how a
mate thinks and responds for a specific goal. They are not OpenCode modes,
editor modes, OS notification modes, or backend app skills.

## Arguments

Parse `$ARGUMENTS` as optional hints:
- `appId` — parent OpenMates app directory, such as `web`, `code`, `jobs`, or `study`
- `focusId` — runtime focus mode id, snake_case preferred, such as `career_insights`

If either value is missing, infer it during discovery or ask during the
clarifying rounds. Do not invent a final app or ID without user confirmation.

## Workflow

Follow this structure closely. The user expects a deliberate plan-before-build
flow with two clarification blocks and a draft review gate.

### Step 1: Check Existing Focus Modes

First inspect how focus modes already exist and how the target app is
structured.

Read or search these paths as relevant:
- `docs/architecture/apps/focus-modes.md`
- `docs/architecture/apps/focus-modes-implementation.md`
- `docs/user-guide/apps/focus-modes.md`
- `backend/apps/*/focus_modes/*/SKILL.md`
- `backend/apps/{appId}/focus_modes/*/SKILL.md`
- `backend/apps/{appId}/app.yml`
- `frontend/packages/ui/src/i18n/sources/focus_modes/`
- `frontend/packages/ui/src/i18n/sources/app_focus_modes/`
- `frontend/apps/web_app/tests/focus-mode-*.spec.ts`
- `frontend/packages/ui/scripts/generate-apps-metadata.js`

Identify whether the request is:
- creating a new focus mode
- updating an existing focus mode
- migrating a legacy focus mode
- changing prompt behavior only
- changing activation/routing behavior

### Step 2: Ask 3 Clarifying Rounds

Ask exactly one clear question per round and wait for the user's answer before
continuing. Stop early only if the user explicitly says to skip clarification.

Use these topics unless the repo context reveals more urgent blockers:
- Round 1: What user goal should this focus mode solve?
- Round 2: Which app/category should own it, and should it be new or update an existing mode?
- Round 3: When should it activate, and what should be explicitly out of scope?

### Step 3: Search Internal Context

Based on the answers, search internal sources for relevant connected
information and ideas.

Check:
- existing focus modes with similar goals or prompts
- the owning app's `app.yml`, skills, settings/memories, providers, and icons
- GitHub issues for related product ideas, bugs, or prior decisions
- architecture docs and user-guide docs for the affected app/domain
- tests that cover focus mode settings, activation, rejection, mention, or app behavior

Use GitHub Issues by default for tracker searches. Do not create or update an
issue unless the user asks.

### Step 4: Search External Context

Search externally for ideas and best practices relevant to the requested focus
mode.

Use:
- GitHub search for similar AI assistant modes, prompt packages, agent skills,
  Claude skills, or domain-specific assistant workflows
- web search for best practices in the requested domain
- official or authoritative sources when the mode touches health, finance,
  legal, safety, education, jobs, security, privacy, or other high-risk topics

Keep this research practical. Extract patterns that improve the OpenMates focus
mode contract; do not copy prompts wholesale.

### Step 5: Ask 3 More Clarifying Rounds

Ask exactly one clear question per round and wait for the user's answer before
continuing.

These questions must be informed by the internal and external research. Use them
to resolve:
- domain-specific constraints or safety boundaries
- privacy or data-use limits
- success criteria for what a good answer in this mode looks like
- allowed skills/apps and whether the mode should ask before using external data
- how proactive, cautious, structured, or conversational the mate should be

### Step 6: Suggest a Draft

Present a concise draft and ask for feedback before editing product files.

The draft must include:
- display name
- parent app
- runtime focus ID and directory name
- stage (`planning`, `development`, or `production`)
- one-line description
- activation/preprocessor hint
- process bullets shown in settings
- 2-3 “How to use” examples with highlighted trigger words
- system prompt outline or full proposed system prompt
- skills/apps it may rely on
- non-goals
- safety, privacy, and data-use rules

For updates, show a focused diff-style summary of what will change.

### Step 7: Ask for Feedback

Wait for the user's feedback. Do not implement before this gate unless the user
explicitly says to proceed without draft approval.

### Step 8: Finalize the Draft

Incorporate feedback and show the final version briefly. Confirm any remaining
tradeoffs, such as `stage`, activation breadth, or safety wording.

### Step 9: Implement the Focus Mode

Use the current OpenMates implementation reality, not only the future target
architecture.

Primary authoring target:
- `backend/apps/{appId}/focus_modes/{focus-dir}/SKILL.md`

Current compatibility targets that may also need updates:
- `backend/apps/{appId}/app.yml`
- `frontend/packages/ui/src/i18n/sources/focus_modes/{appId}_{focusId}.yml`
- `frontend/packages/ui/src/i18n/sources/app_focus_modes/{appId}.yml`

Rules:
- Runtime `id` in `SKILL.md` is snake_case and must match OpenMates metadata.
- Focus mode directory names are kebab-case for portability.
- Keep `SKILL.md`, `app.yml`, and i18n keys aligned while the migration is incomplete.
- Use `stage: development` for new unverified modes unless the user explicitly asks for `planning` or `production` and the mode is tested.
- `preprocessor-hint` should be 1-3 sentences that describe when to select the mode, not the full system prompt.
- `## Process` bullets should be user-facing and concrete.
- `## System prompt` should define role, workflow, boundaries, tool behavior, and output expectations.
- Capability fields such as `allowed-skills` are currently parsed but not fully enforced at runtime; do not rely on them as the only safety control.
- If translations are not human-reviewed, do not mark localized files as verified by a human.

### Step 10: Validate

Run the smallest checks that prove the change.

Usually relevant:
- `cd frontend/packages/ui && npm run build:translations` after i18n YAML edits
- `cd frontend/packages/ui && npm run generate-apps-metadata` after focus metadata edits, if available in `package.json`
- targeted parser or metadata-generation checks for `SKILL.md`
- relevant lint or typecheck command for changed areas

For any user-facing focus-mode behavior change, run a real OpenMates CLI chat
quality check after the metadata is built and, when testing dev behavior, after
the change is deployed to dev. Use the test-account helper or the compiled CLI,
for example:
- `node scripts/openmates_cli_test_account.mjs login --api-url https://api.dev.openmates.org`
- `node frontend/packages/openmates-cli/dist/cli.js --api-url https://api.dev.openmates.org chats new "<example request>" --json`

Run multiple example requests that match the activation hint and inspect the
actual assistant output. Record whether the focus mode activated, which skills
were used, whether the answer followed the expected structure, and whether the
quality met the draft's success criteria. If the CLI cannot be run, document the
blocking reason instead of treating parser/build checks as behavior evidence.

For user-facing focus-mode behavior, propose the relevant E2E test path and use
the repo test runner after deploy when running Playwright:
- `python3 scripts/tests.py run --spec focus-mode-settings.spec.ts`
- `python3 scripts/tests.py run --spec focus-mode-mention.spec.ts`
- `python3 scripts/tests.py run --spec focus-mode-rejection.spec.ts`
- a new or updated focus-mode-specific spec if needed

Do not run Playwright locally.

### Step 11: Add or Verify an Example Chat

Every production or development focus mode must have at least one permanent
example chat linked from its focus-mode details page. This applies to both new
focus modes and prompt/routing improvements to existing focus modes.

Before finishing:
- Search `frontend/packages/ui/src/demo_chats/data/example_chats/` for an
  existing example with `metadata.app_focus_mode_examples` containing
  `"{appId}.{focusId}"`.
- If none exists, create a real OpenMates chat through the CLI or app, share it,
  and scaffold it with `scripts/create-example-chat-from-share.mjs`.
- Prefer a real CLI chat for reproducibility. If the focus mode needs explicit
  activation, use the CLI focus mention while creating the chat, but remove the
  internal `@focus:...` wire prefix from public example-chat user text after
  scaffolding.
- Set `metadata.app_focus_mode_examples: ["{appId}.{focusId}"]` and
  `metadata.active_focus_id: "{appId}-{focusId}"` on the example chat so the
  focus-mode page can surface it and the demo chat opens with the active focus
  state visible.
- Translate the new example-chat YAML, build translations, validate locales, and
  run `scripts/audit_example_chats.py` before deploying.
- If a real example chat cannot be created, document the blocker explicitly; do
  not silently finish a focus-mode improvement without an example-chat plan.

## Draft Template

Use this structure for Step 6 and Step 8.

```markdown
## Focus Mode Draft

Name:
App:
Focus ID:
Directory:
Stage:

Description:

Activation hint:

Process:
- ...

How to use:
- ...
- ...
- ...

System prompt:
...

Allowed skills/apps:

Non-goals:

Safety and privacy:

Open questions:
```

## Implementation Checklist

Before finishing, verify:
- `SKILL.md` frontmatter starts and ends with `---`
- `id` is snake_case and directory is kebab-case
- title matches the display name intent
- `## Process`, `## How to use`, and `## System prompt` sections exist when needed
- `app.yml` contains or preserves compatible metadata while backend discovery still needs it
- i18n YAML source files contain name, description, process, system prompt, and how-to-use strings where required
- generated translations/metadata were rebuilt if source files changed
- real OpenMates CLI chat requests covered the intended activation behavior and
  output-quality contract for behavior changes
- at least one permanent example chat is linked via
  `metadata.app_focus_mode_examples` for the focus mode
- relevant docs/tests were updated or explicitly deferred

## When to Escalate to a Full Spec

Use `specify` before implementation if the focus mode changes runtime behavior,
adds new persistence, introduces new API routes, changes activation/deactivation
semantics, touches encryption/privacy-sensitive data flows, or requires new app
skills/providers. Pure prompt/content additions can usually follow this skill
without a full spec.
