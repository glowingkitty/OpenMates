# OpenMates AI Assistant Instructions

This repository is optimized for Codex/OpenCode while preserving the existing Claude Code setup.
Do not remove or replace `CLAUDE.md`, `.claude/`, Claude skills, Claude hooks, or Claude session tooling unless the user explicitly asks.

Domain-specific rules are in `.claude/rules/`. OpenCode loads the same rules through `opencode.json`; Codex should follow this file plus those shared Claude-compatible rules.
Full contributing docs are in `docs/contributing/` and can be loaded on demand via `sessions.py context --doc <name>`.

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
│   └── contributing/           # Coding standards, guides
├── vaults/
│   └── memory/                 # Obsidian vault for notes, research, memory, and attachments
└── scripts/                    # sessions.py, lint_changed.sh, test runners
```

---

## Core Principles

- **KISS:** Small, focused, well-named functions. No over-engineering.
- **Clean Code:** Remove unused functions, variables, imports, dead code.
- **No Silent Failures:** Never hide errors with fallbacks. All errors must be visible and logged.
- **No Magic Values:** Extract raw strings/numbers to named constants.
- **Comments:** Explain business logic and architecture decisions. Link to `docs/architecture/`.
- **File headers:** Every new `.py`, `.ts`, `.svelte` file needs a header comment (5-10 lines).
- **Deterministic guardrails:** When repeated bugs, flaky tests, security/privacy risks, provider metadata drift, or OpenCode workflow issues cost debugging time or inference tokens, prefer creating or updating a deterministic script, audit, hook, or focused test guard that prevents the same issue from recurring.

### DRY: Search Before Writing

| Shared location                        | What goes there                            |
| -------------------------------------- | ------------------------------------------ |
| `backend/shared/python_utils/`         | Backend shared logic                       |
| `backend/shared/python_schemas/`       | Shared Pydantic models                     |
| `backend/shared/providers/`            | Pure API wrappers (no skill-specific code) |
| `frontend/packages/ui/src/utils/`      | Frontend shared utilities                  |
| `frontend/packages/ui/src/components/` | Shared Svelte components                   |
| `settings/elements/`                   | Settings UI components (26 component files) |

Architecture decisions: write once in `docs/architecture/`, reference in code.

Whenever asking a clarifying question, include an explicit `Recommendation:`
with the evidence-based preferred answer and brief rationale, plus `Examples:`
with concrete, task-specific options or outcomes. Ask only one decision question
per message; the recommendation and examples are supporting context, not extra
questions. If evidence is incomplete, recommend the safest reversible default
and state the uncertainty.

## Scan-First Final Answers

When a final answer needs more than one sentence, use a scan-first layout. Start
with one state heading: `## ✅ Done`, `## 🚧 Blocked`, `## ❓ Decision Needed`, or
`## 🧠 Investigation`. Prefer compact tables for files, tests, blockers, risks,
and next actions; use short bullets only when a table would be awkward. Keep
narrative paragraphs under three lines. Use icons semantically and sparingly:
`📁` files, `🧪` verification, `⚠️` risk or uncertainty, `➡️` next action, and
`🔧` fix. Do not paste large YAML, JSON, contracts, or logs into blocker
summaries unless the user asks; reference the path or hash and provide one
copy-paste action when useful.

## Agent Workflow Retrospective

For every non-trivial task-closing summary, include a concise retrospective about the agentic process used to fulfill the request, not about the request's product results. Report only observed preventable process problems from the main chat, research, tool use, delegated agents, and sub-chats, such as failed or redundant searches, incorrect skill or agent selection, instruction conflicts, avoidable rereads or tool calls, policy or hook friction, abandoned approaches, missed verification, or coordination failures. Do not repeat implementation results, changed files, discovered product bugs, test outcomes, or remaining product work unless an agent-workflow deficiency caused or unnecessarily prolonged them. Ordinary task difficulty is not a workflow issue.

For each observed preventable process problem, check the relevant existing hooks, skills, agents, agent instructions, and deterministic audits/tests before recommending the smallest concrete workflow improvement. Classify each recommendation as a hook, skill, agent/subagent definition, agent instruction, or deterministic audit/test. Do not recommend new prompt prose when an existing mechanism already covers the issue or a deterministic guard would be more reliable. State when existing coverage is sufficient and no change is warranted. Use `None observed` when no preventable agent-workflow issue occurred. Do not invent problems, expose hidden reasoning, guess durations, or include raw private logs or private chat content. Simple requests, clarification-only turns, and progress updates do not require this section.

---

## Obsidian Vault

- The Obsidian vault lives at `/home/superdev/projects/OpenMates/vaults/memory/` (`vaults/memory/` from the repo root).
- Create user-requested notes in that vault, using existing folders such as `Resources/research/`, `Areas/`, or `Projects/` when appropriate.
- Put PDFs, images, and other attachments in `vaults/memory/assets/` unless the user asks for a different location.

---

## Working Rules

- Make the smallest correct change. Avoid rewrites unless the task requires one.
- Search before adding shared logic. Prefer existing utilities, components, providers, and schemas.
- Add backend shared logic under `backend/shared/python_utils/`, `backend/shared/python_schemas/`, or `backend/shared/providers/`.
- Do not import from another backend skill. Move shared behavior to `BaseSkill` or `backend/shared/`.
- Use the repo scripts rather than ad hoc commands when available.
- OpenMates alpha versioning uses fixed minor trains: product UI `v0.X`, npm/GHCR `0.X.0-alpha.N` / `v0.X.0-alpha.N`, and PyPI `0.X.0aN`. Use `python3 scripts/bump_alpha_version_line.py --minor X` for product-line bumps; do not create `0.X.N-alpha` patch trains.
- A `sessions.py` `modified_files` entry is advisory commit-tracking, never exclusive ownership. Re-read a file and proceed unless a current manual `WRITING` claim or Docker/dev deploy push lock covers the operation. If a manual `WRITING` claim blocks an exact file, treat the short session ID as diagnostic only: check status, work on non-conflicting files, or retry after release. Do not ask the user to interpret the ID or choose an ownership boundary unless all useful progress is blocked.
- App metadata must not use `stage`. Apps, skills, embeds, focus modes, memory fields, and platform features are enabled by default; add sparse `default_enabled: false` only when a feature intentionally ships off by default.
- For new shared features, app skills, focus modes, embeds, memory types, and provider-backed behavior, implement and test in strict order: REST API/WebSocket contract first, real CLI commands on the dev server second, npm SDK and pip SDK locally against the dev server third, web fourth, reviewed Playwright visual smoke fifth for larger deployed UI, user confirmation sixth, Apple parity last. Before adding or changing an endpoint, explicitly classify its access model: unauthenticated public REST API, developer API-key REST API, first-party client surface only (web/CLI/SDK/native with session or approved device auth), or internal-only. Also identify auth requirements, rate limits, credit/budget limits, and whether the endpoint handles client-side encrypted data or decrypted plaintext. Any endpoint that accepts or returns client-side encrypted chat, memory, file, key, sync, or share material must default to first-party or internal-only access unless a spec explicitly approves a narrower public/developer contract that preserves encryption boundaries. REST/CLI/SDK gates must hit the real dev API/WebSocket path at `https://api.dev.openmates.org` with real auth/test-account state; mocked API calls, mocked SDK clients, stubbed servers, direct function calls, and fixture replay do not satisfy them. Only after local dev-server REST, CLI, and SDK tests pass should the same coverage be reproduced or wired into GitHub Actions for CI/daily tests.
- On this dev machine, `https://api.dev.openmates.org` and `https://app.dev.openmates.org` are the current dev server backed by the local Docker stack. After backend/API code changes, restart the affected local Docker service (usually `api`, plus workers only when touched) under the Docker lock before testing the dev URL. Do not wait for GitHub self-host image publishes to make code visible on `api.dev.openmates.org`; those image workflows are for published/self-host artifacts, not the live local dev stack.
- Treat deterministic scripts as a first-class outcome of bug fixes and code-quality work. Prefer updating an existing script over adding a new one; wire checks into hooks only when they are path-scoped, fast, and low-noise, otherwise expose them as on-demand scripts from the relevant skill.
- For Playwright and Vitest, follow `.claude/rules/testing.md`; do not run local test commands that the repo forbids.
- For `*.spec.ts` Playwright verification, deploy the change to `dev` first, wait for the deployment to be live, then run the spec against `https://app.dev.openmates.org` with `python3 scripts/tests.py run --spec <name>.spec.ts --gate-deploy --expected-commit <sha>`. Do not run E2E specs against undeployed local code. If the dispatcher reports that Playwright must run against deployed code, perform the scoped `sessions.py deploy` and rerun the spec; do not stop on a generic missing deploy/commit request unless a safety exception below applies.
- For larger user-visible web/UI changes, run deployed Playwright visual smoke after the relevant Playwright spec and before user confirmation or session completion. Use `node frontend/apps/web_app/scripts/visual-smoke.mjs --url https://app.dev.openmates.org/<route> --session <id>` to capture laptop and mobile screenshots, then inspect those screenshots and record a passed `sessions.py visual-smoke` entry only with a summary containing `Defects:` and `Accepted differences:`. Fix objective clipping, overlap, overflow, hidden controls, broken media, implementation error text, long loading/spinner states, console-visible failures, or unresponsive primary controls; redeploy and rerun before marking done. Use Firecrawl only as an explicit fallback when Playwright cannot inspect the route practically, keep calls minimal, and record why. Skip only for Tier 0/non-visual work with an explicit reason.
- Every new feature implementation, every new hardcoded example chat, and every nightly/daily/CI failed E2E that is actively debugged in a chat and turns green requires proof-video evidence before session completion. First use `create-demo-video` and `python3 scripts/proof_video_workflow.py start --current --spec <name>.spec.ts` with passing real CLI or deployed Playwright evidence. Burn the approved tutorial transcript into bottom-centered captions; narration audio is optional. Web/spec/example-chat proof uses separate phone and laptop videos, Apple proof uses separate iPhone portrait and iPad landscape videos, and CLI proof uses one terminal video. Review only the bounded frame bundle plus transcript; objective defects such as clipping, premature truncation, wrong icons or gradients, raw protocol/error text, missing processing animation, stale loading states, or broken navigation must return to failing-test and implementation work. When the Discord proof destination is configured, confirmed Discord delivery is a hard completion gate.
- For shared product behavior exposed outside the browser, verify the direct REST API/WebSocket contract, CLI, npm SDK, and pip SDK contracts locally against `https://api.dev.openmates.org` before web Playwright. Run `python3 scripts/audit_sdk_cli_parity.py` when touching CLI commands, SDK facades, app skills, settings-backed chat behavior, embeds, billing, notifications, or benchmark behavior.
- For cross-client changes, prefer `python3 scripts/verify_parity.py --run --web-spec <spec>.spec.ts --apple build` to enforce the REST/API → CLI/SDK → web → reviewed Playwright visual smoke → user confirmation → Apple order and write evidence. Use explicit `--skip-web` or `--apple skip --skip-apple "reason"` only when the surface is truly unaffected.
- For changed code, run the smallest relevant lint/test/build command that proves the change; for larger deployed UI work, also record `python3 scripts/sessions.py visual-smoke --session <id> --viewport laptop --viewport mobile ...` evidence before ending the session.
- Firecrawl MCP tools are quota-backed and project ask-gated. Do not use Firecrawl for routine docs/API research, routine web search, or routine OpenMates UI validation. Prefer Context7 for library docs, Brave/WebFetch for general web research, and Playwright for OpenMates visual validation; use Firecrawl only when those cannot produce the needed evidence, keep calls tightly bounded, and explain the reason.
- If verification is not run, state why.

---

## Safety Rules

- Never delete, rewrite, or disable Claude Code setup files unless explicitly requested.
- Never use destructive git commands such as `git reset --hard` or `git checkout --` unless explicitly requested.
- Never change the repository default branch away from `dev`, and never switch the local working tree away from `dev`. `dev` is the permanent default/current working branch for agents.
- Never create PRs, merge branches, publish releases, use `git stash`, or run raw `git worktree` commands unless explicitly requested. Use `python3 scripts/sessions.py worktree ensure --session <id>` for orchestrated agent worktrees.
- Treat secrets, credentials, production keys, `.env` files, and private tokens as off-limits.
- This is open source. Use `<PLACEHOLDER>` values for domains, emails, SSH keys, IPs, API keys, and private repo URLs.
- Committing and pushing to `dev` via `sessions.py deploy` is not destructive; it is expected after every task.
- Do not ask for permission before a scoped `dev` deploy through `sessions.py deploy` when deployment is required to verify assigned work; this instruction is the repo-level authorization for deployed Playwright, Vercel, GitHub Actions, CLI/SDK, and Apple parity verification. Ask first for production deploys, raw git commit/push, broad or unscoped dirty deploys, destructive data/migrations, secrets, unclear privacy/billing/security scope, same-file overlap that cannot be safely staged, or when the user requested planning/review only.
- `python3 scripts/sessions.py deploy` acquires the dev deploy push lock only for root integration, commit, and push, then releases it immediately after push. Do not run a separate `wait-lock` before normal deploys; use `wait-lock` only for diagnostics/manual inspection. Vercel and test verification must be commit-scoped with `--expected-commit`, not protected by a long-lived global lock.

---

## OpenCode Behavior

- Prefer OpenCode-native config in `opencode.json` for this repo.
- OpenCode is the primary agentic coding workflow for this repository. Keep Claude files as compatibility/shared-rule sources for other contributors and because OpenCode loads the shared `.claude/rules/` guidance through `opencode.json`.
- Existing Claude Code skills in `.claude/skills/` are intentionally retained; OpenCode uses the `.agents/skills/` mirror and must not call the Claude Code runtime.
- Codex discovers repo skills from `.agents/skills/`. Keep `.agents/skills/` as the Codex/OpenCode-compatible mirror of `.claude/skills/`, using Agent Skills compliant names (`lowercase-hyphenated`, matching the folder name).
- Do not add project skills under `.codex/skills/` or `.opencode/skills/` unless a tool-specific override is explicitly needed; use `.agents/skills/` for shared skills.
- OpenCode must not load the Claude Code provider. Generated `.opencode/agents/` subagents use explicit GPT-5.6 Luna, Terra, or Sol routes at medium reasoning effort based on workload risk; built-in `explore` and `general` use Terra at medium effort.
- Existing Claude Code hooks are bridged through `.codex/hooks/claude-hook-bridge.sh`: Codex calls it from `.codex/hooks.json`, and OpenCode calls it from its native `.opencode/plugins/openmates-hooks.js` wrapper. Update the bridge instead of duplicating hook logic.
- Claude Code remains the canonical authoring format for project skills, subagents, and hook scripts. Run `python3 scripts/sync_agent_parity.py` after changing `.claude/skills/` or `.claude/agents/`, and run `python3 scripts/sync_agent_parity.py --check` to verify `.agents/skills/`, `.codex/agents/`, `.opencode/agents/`, and hook adapters are in sync.
- For the short agent workflow entry point, read `docs/contributing/guides/agent-workflow-quickstart.md`. Run `python3 scripts/audit_opencode_output_quality.py` after changing OpenCode instructions and `python3 scripts/audit_agent_tooling_parity.py` after changing Claude/Codex/OpenCode hook or config coverage.
- Do not add GSD/Get-Shit-Done workflows, commands, hooks, or agents to this repo.
- If GSD files appear from global OpenCode config, treat them as unrelated user-level tooling and keep them disabled for OpenMates work.

### Skill Auto-Selection

Use OpenCode skills proactively when the task matches their purpose. Do not wait
for the user to name the skill if the intent is clear.

Spec-driven development:
- Use the risk tiers in `docs/contributing/guides/spec-driven-development.md`. Auto-select `specify` for Tier 2 high-risk or durable multi-session work; use a concise inline contract for ordinary Tier 1 work instead of forcing a full YAML ledger.
- Full specs are required for auth, encryption, billing, privacy, teams, sharing, permissions, sync, AI pipeline changes, provider integrations, migrations, new API routes, app skills, embed types, background jobs, cron jobs, and Directus schema changes.
- Full specs use one executable YAML source of truth at `docs/specs/<slug>/spec.yml`; do not create separate Markdown spec, plan, or task files for new specs.
- New full specs declare `schema_version: 2`; active legacy specs migrate only when materially resumed. Schema V2 records approvals, decisions, attempts, handoff, task ownership, and evidence subject commits in the same `spec.yml`.
- Before writing `spec.yml`, discover existing GitHub Issues, relevant Linear tasks only when appropriate, docs, source patterns, and tests; then ask up to five rounds of clarifying questions, one question per message. Wait for the user's response before asking the next question, then wait for the user's vision confirmation before writing the final full spec.
- Use `plan-from-spec` and `tasks-from-spec` after a full spec is approved; they update `implementation_plan` and `tasks` inside `spec.yml`.
- Write or update the tests listed in `spec.yml` before feature code. Record red-phase evidence before implementation. For Playwright, red and green runs target live `app.dev.openmates.org`; green evidence is only valid after deploy and Vercel is Ready.
- For new shared functionality, direct REST API/WebSocket tests run first locally against the dev server, followed by real CLI commands and npm/pip SDK calls against the same server. These gates must not mock OpenMates API/WebSocket calls. Only after local REST, CLI, and SDK proof passes should the same coverage move or wire into GitHub Actions for CI/daily tests. Web, user confirmation, and Apple work wait for real dev-server REST, CLI, and SDK proof when those surfaces apply.
- Run `python3 scripts/spec_validate.py docs/specs/<slug>/spec.yml` after spec edits and `python3 scripts/spec_verify.py docs/specs/<slug>/spec.yml` before marking the spec complete or deploying full-spec work.
- Once an approved spec or session task is implementing, continue through all actionable tasks and failed checks. Pause only for important unresolved user input; task size, context pressure, test failures, and temporary file waits are not completion states.
- Record evidence with the command, run ID, timestamp, and tested subject commit. A material contract, test, assumption, or implementation change invalidates linked green evidence until replacement evidence is recorded.
- Use an inline spec instead of a full spec for small behavior changes; skip specs for trivial or mechanical work. See `docs/contributing/guides/spec-driven-development.md` for the boundary.

Common routing:
- Figma artboard lookup or design-referenced web/Apple UI work: use `figma-reference` before implementation.
- New external API/provider: use `add-api`.
- New backend app skill: use `add-app-skill`.
- New embed type: use `add-embed-type`.
- New hardcoded example chat from a share URL: use `add-example-chat`.
- User-visible bug with reproducible behavior: use `reproduce-first` before fix code.
- Latest failing tests or daily-run failures: use `fix-tests` or `fix-next-test`.
- User-reported issue ID or debugging timeline: use `debug-issue`; for encryption/key/sync symptoms, use the encryption/debug specialist subagents from the available agent list.
- Vercel deployment failure: use `fix-vercel`.
- Production SSH request: use `prod-ssh`.
- Newsletter creation/publishing: use `create-newsletter` or `publish-newsletter`.
- iOS/macOS parity work: use `ios`.
- Task creation or prioritization: use `new-task` or `next-tasks`.

If multiple skills apply, choose the earliest workflow gate first. For example,
for a new provider-backed app skill, run `specify` or `add-api` research before
scaffolding with `add-app-skill`; for a bug, reproduce with a failing test
before implementation.

### Reported Issue Workflow

- The reported issue database is the source of truth for user-submitted issue IDs; GitHub and Linear are secondary links, not the starting point.
- Use `python3 scripts/issues.py show <issue-id> --env prod` and `python3 scripts/issues.py findings <issue-id> --env prod` before product-code changes. Use `--env dev` only when the report is known to be from dev.
- For production reports, inspect the production code on `main` first (`git fetch origin main:refs/remotes/origin/main` then `git show origin/main:<path>`). Use the current `dev` branch only after that to check whether dev is also susceptible to the same issue, bug, or behavior, or whether dev already contains a fix.
- Store local-only investigation notes under `docs/findings/issues/<env>/<YYYY>/` and update them with first anomaly, root-cause hypothesis, related reports, attempts, tests, and status. This folder is gitignored; do not store reported-issue findings elsewhere or commit them.
- Prefer `scripts/issues.py list`, `cluster`, `recent`, and `timeline` over raw `debug.py issue` commands. Keep `debug.py` for low-level forensic/admin actions that the workflow wrapper does not expose.
- Redact private user data and share URL `#key=` fragments in findings notes.

---

## Lazy-Load Rules

Use the repo rule files when the task touches relevant areas. In OpenCode, these are also listed in `opencode.json` instructions.

- Frontend work: `.claude/rules/frontend.md`
- Design/UI/media work: `DESIGN.md`
- Backend work: `.claude/rules/backend.md`
- Tests or test failures: `.claude/rules/testing.md`
- Privacy/legal/provider work: `.claude/rules/privacy.md`
- Settings UI: `.claude/rules/settings-ui.md`
- i18n: `.claude/rules/i18n.md`
- Deployment/session lifecycle: `.claude/rules/deployment.md` and `.claude/rules/session-lifecycle.md`
- Debugging: `.claude/rules/debugging.md`
- Embeds: `.claude/rules/embed.md`
- Apple UI: `.claude/rules/apple-ui.md`
- Planning and acceptance criteria: `.claude/rules/planning.md`
- Task tracking workflow: `.claude/rules/task-management.md` — GitHub Issues by default; Linear only for programmatically stored/recorded issues, marketing work, sensitive/private work, or explicitly provided Linear issues.

---

## Parallel Work: Spawning Separate Sessions

You can suggest spawning parallel OpenCode chats for independent tasks.
Always ask the user for confirmation before spawning.
Spawned chats are persisted OpenCode Web chats in the same project sidebar;
they do not create separate Zellij sessions.

```bash
# Spawn a planning/research session (default: plan mode, read-only)
python3 scripts/sessions.py spawn-chat --prompt "Research how X works" --name "research-x"

# Spawn with a prompt file
python3 scripts/sessions.py spawn-chat --prompt-file scripts/.tmp/prompt.txt --name "plan-task"

# Spawn with full edit access (only when user explicitly requests direct fix/implementation)
python3 scripts/sessions.py spawn-chat --prompt-file scripts/.tmp/fix-prompt.txt --name "fix-OPE-42" --mode execute
```

The spawned chat must start its own `sessions.py` session before mutating work. Use the returned OpenCode session ID or sidebar URL to inspect it.

```bash
# Read an existing OpenCode chat from a session ID or code.dev URL
python3 scripts/sessions.py chat read ses_...
python3 scripts/sessions.py chat read "https://code.dev.openmates.org/<project>/session/ses_..."

# Search a chat for hook, worktree, tool, or error evidence
python3 scripts/sessions.py chat search ses_... "worktree"

# Long form is also supported: opencode-chat read/search
```

**When to suggest:** Multiple independent tasks, post-meeting planning, parallel research.
**When NOT to:** Tasks with file conflicts, sequential dependencies, or when the user prefers focused work.
**Default is plan mode.** Only use `--mode execute` when the user makes it very clear the task should be directly implemented by the spawned session.

---

## Research Before New Integrations

Before any new app, skill, API integration, or significant feature:

1. Search existing tracker entries before creating new ones. Use GitHub Issues by default. Use `python3 scripts/linear.py` only for programmatically stored/recorded issues, marketing work, sensitive/private work, or explicitly provided Linear issues.
2. Search for official docs (never rely on training data for APIs/pricing).
3. Check `docs/architecture/apps/`, `docs/architecture/`, and `docs/user-guide/apps/` for existing research.
4. Ask clarifying questions before writing code. Wait for confirmation.
