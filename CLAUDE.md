# OpenMates AI Assistant Instructions

Domain-specific rules are in `.claude/rules/` — loaded automatically by file path context.
Full contributing docs are in `docs/contributing/` — loaded on demand via `sessions.py context --doc <name>`.

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
│   └── contributing/           # Coding standards, guides (loaded by rules via @import)
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

## Contract-Driven Development

- Approved bundles under `specifications/` define durable truth. New reusable behavior uses `define-specification` before a Plan or implementation.
- Specification edits stay in the session worktree and require exact user approval through the generated approval PDF, then record the approved bundle hash. Later edits invalidate approval and deploy blocks.
- Full specs remain complete implementation/evidence ledgers. New or changed behavioral tests link stable contract assertions and surfaces; touched unmapped tests trigger backfill.
- Reference contracts from specs, tests, commits, and releases, not product source headers.

### DRY — Search Before Writing

| Shared location                        | What goes there                            |
| -------------------------------------- | ------------------------------------------ |
| `backend/shared/python_utils/`         | Backend shared logic                       |
| `backend/shared/python_schemas/`       | Shared Pydantic models                     |
| `backend/shared/providers/`            | Pure API wrappers (no skill-specific code) |
| `frontend/packages/ui/src/utils/`      | Frontend shared utilities                  |
| `frontend/packages/ui/src/components/` | Shared Svelte components                   |
| `settings/elements/`                   | Settings UI components (29 canonical)      |

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

For every non-trivial task-closing summary, include a concise retrospective about the agentic process used to fulfill the request, not about the request's product results. Report only observed preventable process problems and inefficiencies from the main chat, research, tool use, delegated agents, and sub-chats, such as failed or redundant searches, incorrect skill or agent selection, instruction conflicts, avoidable rereads or tool calls, unnecessary retries, avoidable context growth, wasted subagent runs, policy or hook friction, abandoned approaches, missed verification, or coordination failures. Include only inefficiencies that wasted agent cycles, context, tool calls, subagent runs, retries, or inference tokens and could plausibly have been prevented by better deterministic scripts, hooks, focused audits/tests, skills, agent/subagent definitions, or runtime instructions. Do not repeat implementation results, changed files, discovered product bugs, test outcomes, or remaining product work unless an agent-workflow deficiency caused or unnecessarily prolonged them. Ordinary task difficulty is not a workflow issue.

For each observed preventable process problem or inefficiency, check the relevant existing hooks, skills, agents, agent instructions, and deterministic audits/tests before recommending the smallest concrete workflow improvement. Classify each recommendation as a hook, skill, agent/subagent definition, agent instruction, or deterministic audit/test. Do not recommend new prompt prose when an existing mechanism already covers the issue or a deterministic guard would be more reliable. Ground efficiency claims in observable actions only; do not estimate token counts or durations. State when existing coverage is sufficient and no change is warranted. Use `None observed` when no preventable agent-workflow issue occurred. Do not invent problems, expose hidden reasoning, guess durations, or include raw private logs or private chat content. Simple requests, clarification-only turns, and progress updates do not require this section.

## Obsidian Vault

- The Obsidian vault lives at `/home/superdev/projects/OpenMates/vaults/memory/` (`vaults/memory/` from the repo root).
- Create user-requested notes in that vault, using existing folders such as `Resources/research/`, `Areas/`, or `Projects/` when appropriate.
- Put PDFs, images, and other attachments in `vaults/memory/assets/` unless the user asks for a different location.

## OpenCode Response Media

- To embed generated images, videos, or PDFs in an OpenCode assistant response, run `python3 scripts/opencode_response_media.py <path> --alt "Description"` and paste the returned Markdown or HTML snippet.
- The helper uploads plaintext media to a private Hetzner S3 bucket with 48-hour object expiry and a 48-hour presigned URL; treat the URL as a temporary bearer token.
- Use this only for intentionally shareable screenshots, diagrams, synthetic test media, or demo clips. Do not upload secrets, private user data, raw logs, production evidence, or anything that must remain available after 48 hours.
- Every assistant message that embeds a video as test evidence must also show the video's filename or repository-relative artifact path next to the embedded player. For UI component test videos, the same message must also include a clickable link to that component's exact deployed `https://app.dev.openmates.org/dev/preview/{component-path}` page. These references are required metadata and never replace the embedded video.
- Every visual inspection, focused test, screenshot, and recording of a `/dev/preview/{component-path}` page must use a bare URL containing `chrome=0`; never inspect or record its configuration UI. Use the `.preview.ts` default fixture for the standard state, and encode every non-default input or configuration in URL query parameters such as `variant`, `props`, `theme`, `background`, and `width`.
- External video playback in OpenCode Web requires the `code.dev.openmates.org` CSP to allow `media-src https:`; if video controls render but playback fails, verify Caddy applied `deployment/dev_server/Caddyfile`.
- When a screenshot or short clip materially helps explain a visual UI state, bug fix, visual-smoke result, proof-video, or implementation defect, include the uploaded media directly in the chat response instead of only naming an artifact path.
- Before asking the user to approve a new or modified Specification, run `python3 scripts/sessions.py specification approval-pdf --session <session-id> --bundle <bundle> --baseline-ref HEAD` and paste the returned PDF Markdown link in the same response. This canonical wrapper runs `scripts/specification_approval_pdf.py` against the routed session worktree. The exact-fingerprint PDF must show the complete Specification and examples with changed-text-only diffs: inline green `+` insertions, inline red `-` deletions, and neutral unchanged text. After explicit approval, pass the generated JSON review artifact to `scripts/specifications.py approve --review-artifact <path>` so the receipt cannot bind a different fingerprint or PDF. Never request or record Specification approval from a fingerprint or summary alone; repair PDF generation or upload first if it fails.

---

## Destructive Actions — Explicit Consent Only

- **NEVER** create PRs, merge branches, publish releases, or use `git stash` unless the user explicitly asks.
- **NEVER** run raw git worktree commands (`git worktree add`) unless explicitly requested. Use `python3 scripts/sessions.py worktree ensure --session <id>` for orchestrated agent worktrees.
- **Committing and pushing to `dev` via `sessions.py deploy` is NOT destructive** — it is expected after every task.
- Do not ask before a scoped `dev` deploy via `sessions.py deploy` when deployment is required for verification. This includes Playwright `*.spec.ts` verification, which must run against deployed `https://app.dev.openmates.org` code with `python3 scripts/tests.py run --spec <name>.spec.ts --gate-deploy --expected-commit <sha>` after Vercel is Ready. Ask first for production deploys, raw git commit/push, broad dirty deploys, destructive data/migrations, secrets, unclear privacy/billing/security scope, unsafely overlapping same-file edits, or planning/review-only requests.
- `python3 scripts/sessions.py deploy` acquires the dev deploy push lock only for root integration, commit, and push, then releases it immediately after push. Do not run a separate `wait-lock` before normal deploys; use `wait-lock` only for diagnostics/manual inspection. Vercel and test verification must be commit-scoped with `--expected-commit`, not protected by a long-lived global lock.
- This is **open-source**: use `<PLACEHOLDER>` values for domains, emails, SSH keys, IPs, API keys, repo URLs.

---

## Parallel Work — Spawning Separate Sessions

You can suggest spawning parallel OpenCode chats for independent tasks.
**Always ask the user for confirmation before spawning.**
Spawned chats are persisted OpenCode Web chats in the same project sidebar;
they do not create separate Zellij sessions.

```bash
# Spawn a planning/research session (default: plan mode, read-only)
python3 scripts/sessions.py spawn-chat --prompt "Research how X works" --name "research-X"

# Spawn with a prompt file
python3 scripts/sessions.py spawn-chat --prompt-file scripts/.tmp/prompt.txt --name "plan-task"

# Spawn with full edit access (only when user explicitly requests direct fix/implementation)
python3 scripts/sessions.py spawn-chat --prompt-file scripts/.tmp/fix-prompt.txt --name "fix-OPE-42" --mode execute
```

The spawned chat must start its own `sessions.py` session before mutating work. Use the returned OpenCode session ID or sidebar URL to inspect it.

```bash
python3 scripts/sessions.py chat read ses_...
python3 scripts/sessions.py chat read "https://code.dev.openmates.org/<project>/session/ses_..."
python3 scripts/sessions.py chat search ses_... "worktree"

# Long form is also supported: opencode-chat read/search
```

**When to suggest:** Multiple independent tasks, post-meeting planning, parallel research.
**When NOT to:** Tasks with file conflicts, sequential dependencies, or when the user prefers focused work.
**Default is plan mode.** Only use `--mode execute` when the user makes it very clear the task should be directly implemented by the spawned session.

---

## Research Before New Integrations

Before any new app, skill, API integration, or significant feature:
1. **Check existing tracker entries** — use GitHub Issues by default. Use `python3 scripts/linear.py` only for programmatically stored/recorded issues, marketing work, sensitive/private work, or explicitly provided Linear issues. Do not use Linear MCP tools.
2. Search for official docs (never rely on training data for APIs/pricing).
3. Check `docs/architecture/apps/`, `docs/architecture/`, and `docs/user-guide/apps/` for existing research.
4. Ask clarifying questions before writing code. Wait for confirmation.
