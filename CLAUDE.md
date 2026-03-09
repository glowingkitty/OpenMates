# OpenMates AI Assistant Instructions

Essential guidelines for AI assistants. Detailed standards are loaded automatically via the tag system at session start.

---

## MANDATORY: Session Lifecycle (Do This First and Last)

**Every session must run these commands — no exceptions:**

```bash
# 1. FIRST thing:
python3 scripts/sessions.py start --task "brief description"
# → Saves session ID (e.g. "a3f2"). Use this ID in ALL subsequent commands.
# → Auto-infers tags from task (override: --tags "frontend,debug").
# → Prints: git status, recent commits, active sessions, relevant instruction docs.
# → READ the instruction docs — they contain project-specific rules.

# 2. After EVERY file edit/create:
python3 scripts/sessions.py track --session <ID> --file path/to/file.py

# 3. Deploy (lint + commit + push):
python3 scripts/sessions.py deploy-docs                  # load git/deployment docs
python3 scripts/sessions.py prepare-deploy --session <ID> # preview
python3 scripts/sessions.py deploy --session <ID> --title "fix: description" --message "body" --end
# → --end auto-closes the session after successful push.

# 4. If not using --end above:
python3 scripts/sessions.py end --session <ID>
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

| Shared location | What goes there |
|---|---|
| `backend/shared/python_utils/` | Backend shared logic |
| `backend/shared/python_schemas/` | Shared Pydantic models |
| `backend/shared/providers/` | Pure API wrappers (no skill-specific code) |
| `frontend/packages/ui/src/utils/` | Frontend shared utilities |
| `frontend/packages/ui/src/components/` | Shared Svelte components |

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

### No Private Infrastructure in Committed Files

This is open-source. Use `<PLACEHOLDER>` values for: domains, emails, SSH keys, IPs, API keys, repo URLs.

### Logging

Only remove debug logs after user confirms the issue is fixed.

### Issue Resolution

After user confirms fix: `docker exec api python /app/backend/scripts/debug.py issue <id> --delete --yes`

---

## Task Completion Summary

**End every task with this structured summary:**

```
## Task Summary

🏷️ Type: <Bug Fix | Feature | Refactor | Docs | Test>
🔗 Commit: <short-sha>
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

- **Vercel failures:** `python3 scripts/sessions.py debug-vercel`
- **Default assumption:** Issues are on the **dev server**, reported by an **admin**.
- **Git/deployment docs:** Deferred to deploy phase via `python3 scripts/sessions.py deploy-docs`.
