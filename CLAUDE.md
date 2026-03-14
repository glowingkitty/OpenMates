# OpenMates AI Assistant Instructions

Essential guidelines for AI assistants. Detailed standards are loaded automatically via the tag system at session start.

---

## MANDATORY: Session Lifecycle (Do This First and Last)

**Every session must run these commands — no exceptions:**

**Absolute order requirement:** `sessions.py start` must be the very first action in a task, before any file search, file read, context lookup, debugging command, or other repository operation.

**Completion requirement:** `sessions.py end` must always be called when the task is complete (either explicitly with `sessions.py end` or implicitly via `sessions.py deploy --end`). No session may be left open.

```bash
# 1. FIRST thing — MUST include --mode:
python3 scripts/sessions.py start --mode <MODE> --task "brief description"
# → --mode is REQUIRED. Choose one:
#     feature  — implementing new functionality or refactoring
#     bug      — debugging an issue (auto-shows health, recent issues, error overview)
#     docs     — writing or updating documentation
#     question — answering a question about the codebase (minimal output)
#     testing  — working on tests (auto-shows last run results, daily trend, E2E spec inventory, OpenObserve test events)
#
# → Saves session ID (e.g. "a3f2"). Use this ID in ALL subsequent commands.
# → Auto-infers tags from task (override: --tags "frontend,debug").
# → Mode controls which context sections are shown (health, issues, project index, etc.)
# → READ the instruction docs — they contain project-specific rules.
#
# IMPORTANT: When you already have an issue/chat/embed/user ID, pass it DIRECTLY
# in the start command — do NOT call start first and fetch the data separately.
# This saves a full round trip by prefetching everything in one command:
#
#   python3 scripts/sessions.py start --mode bug --task "fix issue" --issue <ISSUE_ID>
#   python3 scripts/sessions.py start --mode bug --task "debug chat" --chat <CHAT_ID>
#   python3 scripts/sessions.py start --mode bug --task "fix embed" --embed <EMBED_ID>
#   python3 scripts/sessions.py start --mode bug --task "check errors" --logs          # last 10 min
#   python3 scripts/sessions.py start --mode bug --task "..." --logs "since=30,level=error"
#   python3 scripts/sessions.py start --mode bug --task "debug user" --user <EMAIL>
#   python3 scripts/sessions.py start --mode bug --task "check debug logs" --debug-id <DBG_ID>
#
# All flags auto-add relevant tags AND inline the fetched data into the session output.

# 2. After EVERY file edit/create:
python3 scripts/sessions.py track --session <ID> --file path/to/file.py

# 3. Deploy (lint + commit + push):
python3 scripts/sessions.py deploy-docs                  # load git/deployment docs
python3 scripts/sessions.py prepare-deploy --session <ID> # preview
python3 scripts/sessions.py deploy --session <ID> --title "fix: description" --message "body" --end
# → --end auto-closes the session after successful push.

# 4. If not using --end above:
python3 scripts/sessions.py end --session <ID>
# → MANDATORY at task completion when deploy was not run with --end.
```

### On-Demand Doc Loading

```bash
python3 scripts/sessions.py context --doc <name>   # e.g. debugging-ref, embed-types-ref
```

### Infrastructure Locks (Docker/Vercel)

```bash
python3 scripts/sessions.py lock --session <ID> --type docker   # before rebuild
python3 scripts/sessions.py unlock --session <ID> --type docker # after rebuild
```

---

## Project Overview

**Frontend:** Svelte 5/SvelteKit, TypeScript, CSS Custom Properties
**Backend:** Python/FastAPI, PostgreSQL/Directus CMS, Docker microservices

```
OpenMates/
├── frontend/
│   ├── apps/web_app/           # SvelteKit web application
│   └── packages/ui/            # Shared UI components, services, stores, i18n
├── backend/
│   ├── apps/                   # Application modules (ai, web, etc.)
│   ├── core/                   # Core API, workers, monitoring
│   ├── shared/                 # Shared utilities, schemas, providers
│   └── tests/
├── docs/
│   ├── architecture/           # Architecture decision docs
│   └── claude/                 # Instruction docs (loaded by tags)
└── scripts/                    # sessions.py, lint_changed.sh, test runners
```

---

## Core Principles

- **KISS:** Small, focused, well-named functions. No over-engineering.
- **Clean Code:** Remove unused functions, variables, imports, dead code.
- **No Silent Failures:** Never hide errors with fallbacks. All errors must be visible and logged.
- **No Magic Values:** Extract raw strings/numbers to named constants.
- **Comments:** Explain business logic and architecture decisions. Link to `docs/architecture/`.

### DRY — Search Before Writing

Before writing any new function, class, model, or component — **search for existing implementations:**

| Shared location                        | What goes there                            |
| -------------------------------------- | ------------------------------------------ |
| `backend/shared/python_utils/`         | Backend shared logic                       |
| `backend/shared/python_schemas/`       | Shared Pydantic models                     |
| `backend/shared/providers/`            | Pure API wrappers (no skill-specific code) |
| `frontend/packages/ui/src/utils/`      | Frontend shared utilities                  |
| `frontend/packages/ui/src/components/` | Shared Svelte components                   |

- **Embed components:** Always use `UnifiedEmbedPreview.svelte` / `UnifiedEmbedFullscreen.svelte` as base.
- **External images:** Use `proxyImage()` / `proxyFavicon()` from `imageProxy.ts`.
- **Architecture decisions:** Write once in `docs/architecture/`, reference in code.

### Module Boundaries

- **Skills** must NOT import from other skills. Shared logic → `BaseSkill` or `backend/shared/`.
- **Stores** must NOT import from other stores' internal modules. Use barrel exports.
- **Providers** must NOT depend on skill-specific code.

### File Standards

Every new `.py`, `.ts`, `.svelte` file needs a header comment (5-10 lines): purpose, architecture context link, test references.

---

## Critical Rules

### State Understanding Before Acting

Before planning or writing any code, state your interpretation of the task and wait for confirmation. For bugs: expected vs actual behavior, which system is responsible. See loaded `planning.md` for format.

### Acceptance Criteria Before Implementing

Every non-trivial task needs a checklist of verifiable acceptance criteria before implementation. For reproducible bugs, include a Firecrawl browser verification step.

### Unexpected Failures

If you hit a failure **not related to your task**: STOP. Check `git log -5 -- <broken-file>`. If your session didn't change it, report to user.

### Debugging Attempt Limit

**2 tries max** with the same approach. Then STOP, summarize, ask user how to proceed.

### Concurrent Sessions

- **Re-read files before editing** if you haven't touched them recently.
- **Check git status** before committing — another session may have committed.
- If a service appears down, check if another session is rebuilding Docker containers.
- Use `sessions.py lock/unlock` for Docker rebuilds and Vercel deploys.

### Auto-Commit After Every Task

Always commit and push to `dev` after completing work. Use `sessions.py deploy`. Track all modified files first. For significant routing/Vite config changes, also run `pnpm build` in `frontend/apps/web_app/`.

### Research Before New Integrations

Before any new app, skill, API integration, or significant feature:

1. Search for official docs (never rely on training data for APIs/pricing).
2. Check `docs/apps/` and `docs/architecture/` for existing research.
3. Ask clarifying questions before writing code. Wait for confirmation.

### Privacy Policy Updates

When adding a new third-party provider, update: `shared/docs/privacy_policy.yml`, `i18n/sources/legal/privacy.yml`, `legal/buildLegalContent.ts`, `config/links.ts`. Also update `lastUpdated` in `privacy-policy.ts`.

### Destructive Actions — Explicit Consent Only

**NEVER** create PRs, merge branches, publish releases, or use `git stash` unless the user explicitly asks.

**Committing and pushing to `dev` via `sessions.py deploy` is NOT a destructive action** — it is the expected default after every task. Do NOT wait for explicit permission to commit and push.

### No Private Infrastructure in Committed Files

This is open-source. Use `<PLACEHOLDER>` values for: domains, emails, SSH keys, IPs, API keys, repo URLs.

### Logging

Only remove debug logs after user confirms the issue is fixed.

### Issue Resolution

After user confirms fix: `docker exec api python /app/backend/scripts/debug.py issue <id> --delete --yes`

### New Features Require E2E Test Proposal (CRITICAL)

After implementing any new **auth flow, payment flow, or user-facing feature**, you MUST propose an E2E test plan describing:

1. The user flow to test (step-by-step)
2. The expected assertions
3. Which existing `*.spec.ts` to extend or which new spec to create

**Wait for user confirmation before writing any test code.** This aligns with Rule 1 in `testing.md` but makes the _proposal_ mandatory, not optional.

### Sidebar-Closed as Default Test Scenario

When testing any chat-related feature, always verify with the **sidebar defaulting to closed** (the current default for viewports <=1440px). Five consecutive bugs were caused by stores assuming the sidebar component was mounted.

### Cold-Boot Verification

After fixing a chat, navigation, or sync bug, verify by **clearing IndexedDB and localStorage** in the browser, then reloading. Five bugs only manifested on cold boot with empty cache.

### Two-Commit Rule for Refactors

When moving a function between modules (e.g., class method to module-level function), **ALL call sites must be updated in the same commit**. Never split a refactor across commits where intermediate states break imports. Run unit tests before committing.

### Cache-Miss Fallback Pattern (Backend)

Cache reads MUST have a database fallback. **Never treat a cache miss as a terminal error.** Pattern:

```python
value = await cache.get(key)
if value is None:
    value = await db.get(key)
    await cache.set(key, value)
```

### Required Props Over Optional Props (Frontend)

Callback props that are required for functionality (`onFullscreen`, `onClose`, `onSubmit`) MUST be typed as **required**, not optional. If a prop is sometimes not needed, use two component variants or a discriminated union type.

### Use Playwright Specs for Verification (Not Firecrawl)

For feature/fix verification, prefer writing or extending Playwright `*.spec.ts` tests over one-off Firecrawl browser sessions. Specs are repeatable, automated, and don't consume Firecrawl API quota. Reserve Firecrawl for **debugging** when a spec fails and you need to manually investigate.

### GitHub Actions CI

Pushes to `dev` trigger GitHub Actions CI (`.github/workflows/ci.yml`) which runs:

- Frontend: vitest unit tests, svelte-check, i18n validation
- Backend: pytest unit tests (non-integration)
- Failure notifications via internal API email

This is lightweight and external — it does NOT replace the daily E2E cron or Vercel builds.

---

## Task Completion Summary

**Deploy FIRST, then write the summary.** The `Commit:` field requires a real SHA — you can only get it after running `sessions.py deploy`. Writing the summary before deploying is wrong.

```bash
# Required sequence before writing the summary:
python3 scripts/sessions.py deploy-docs
python3 scripts/sessions.py prepare-deploy --session <ID>
python3 scripts/sessions.py deploy --session <ID> --title "type: description" --message "body" --end
# → outputs the commit SHA → paste it into the summary below
```

**End every task with this structured summary:**

```
## Task Summary

🏷️ Type: <Bug Fix | Feature | Refactor | Docs | Test>
🔗 Commit: <short-sha — deploy first via sessions.py deploy, then paste the SHA here>
✨ Goal: <1-2 sentences>

❌ Broken Flow (Before): *(Bug fixes only)*
1. User does X → Y happens (expected: Z)

✅ Flow After:
1. User does X → gets Z

📝 Changes:

| File | Change | Why |
|------|--------|-----|
| `path/to/file.ts:123` | Description | Reason |

🧪 Testing: <what was tested, how, results>
⚠️ Risks: <what could break — or "Low risk">

🔍 Session Processing Issues: *(omit if none)*
- List obstacles that slowed down or blocked task completion
```

---

## Special Cases

- **Vercel failures:** Use these commands — **never** `vercel logs` (fails silently on ERROR deployments):
  ```bash
  python3 scripts/sessions.py debug-vercel          # auto-starts session + shows errors/warnings
  python3 backend/scripts/debug.py vercel           # errors/warnings only (fastest)
  python3 backend/scripts/debug.py vercel --all     # full build log
  python3 backend/scripts/debug.py vercel --n 3     # last 3 deployments
  python3 backend/scripts/debug.py vercel --url <deployment-id>  # specific deployment
  ```
- **Default assumption:** Issues are on the **dev server**, reported by an **admin**.
- **Git/deployment docs:** Deferred to deploy phase via `python3 scripts/sessions.py deploy-docs`.

### Vercel Deployment — Wait Before Testing

**ALWAYS wait for Vercel deployment to complete before using Firecrawl (or any browser-based tool) to verify a bug fix or new feature.**

1. After `sessions.py deploy`, check deployment status:
   ```bash
   python3 backend/scripts/debug.py vercel           # confirm latest deployment succeeded
   ```
2. Do NOT run Firecrawl verification until the deployment status is **Ready** (not building, not error).
3. If the deployment fails, fix the build error first — do not test against a stale deployment.
4. Only after confirming deployment is live should you use Firecrawl to verify the fix/feature works in production.
