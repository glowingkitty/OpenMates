# Agent Workflow Core

OpenCode is the primary OpenMates coding runtime. Claude Code remains the
canonical authoring source for project skills, subagents, hooks, and shared
rules; Codex and OpenCode consume generated or bridged mirrors.

Keep default context concise. Lazy-load detailed rules, docs, and skills only
when the task touches that area: frontend, backend, testing, privacy, settings,
embeds, Apple, specs, deployment, or provider integrations.

OpenCode Web chats intentionally remain at the root project URL. For mutating
work, run `python3 scripts/sessions.py start --mode <mode> --task "..."` before
edits, Bash-heavy investigation, or Task children. Hooks route local reads,
searches, edits, Bash, and children into the session worktree; use repository-
relative paths and do not set Bash `workdir` to root or another checkout. If a
hook rejects a call, follow its `Next:` action instead of retrying the same call.
Reads and lifecycle recovery commands remain available when routing needs repair.

Before editing, discover the relevant files, source patterns, docs, and tests.
Use the smallest correct change. Prefer deterministic audits or focused tests
when repeated mistakes, flaky behavior, safety risks, or workflow drift are
found.

Before issuing tools, collect operations whose inputs are already known and
emit independent calls in one turn. Batch unrelated reads, searches, static
inspections, and disjoint-file patches; keep calls sequential when one result
selects or validates the next action. When a todo update and the next operation
are independent, issue them in the same turn instead of spending a standalone
model round-trip.

Playwright `*.spec.ts` verification is deployed-code verification. If local UI,
embed, or spec changes are needed, perform a scoped `dev` deploy with
`python3 scripts/sessions.py deploy`, wait for Vercel Ready, then dispatch
`python3 scripts/tests.py run --spec <name>.spec.ts --gate-deploy --expected-commit <sha>`
against `https://app.dev.openmates.org`. This repo instruction authorizes that
scoped deploy; do not stop with a generic "no explicit deploy/commit request"
blocker unless a session-lifecycle safety exception applies.

Final responses should be evidence-based and concise. Name changed files, exact
verification commands, failed checks, skipped checks, and any uncertainty. For
larger deployed UI work, include the Playwright visual-smoke route(s), laptop and
mobile screenshot paths, observed rendering/error/responsiveness findings,
accepted differences, and any fixes made after that review. Do not report visual
smoke as passed from HTTP status or DOM text alone. Firecrawl is quota-backed and
ask-gated; use it only when repo docs, browser/Playwright evidence, or ordinary
web fetches cannot produce the needed evidence. If verification was not run, say
why. Do not include raw private logs, credentials, session titles, prompt text, or
reasoning traces.

Eligible full specs and user-visible Tier 1 plans require an actual captioned
narration video after applicable green gates and before requesting user
confirmation. A test report, screenshots, or visual-smoke evidence alone never
satisfies this gate. Use `create-demo-video` with passing real CLI or deployed
Playwright evidence, review the bounded frame bundle, and give the user the
retained video path or delivery link. Give the active agent the canonical
captions and bounded image frames, never the full video. Use a default
three-second interval plus event boundaries, request exact-timestamp frames only
when needed, and keep Discord publication status separate from the review-based
completion gate. Audio narration remains optional unless explicitly requested.

Common commands:

- `python3 scripts/sync_agent_parity.py --check`
- `python3 scripts/audit_opencode_output_quality.py`
- `python3 scripts/audit_agent_tooling_parity.py`
- `python3 scripts/tests.py run --spec <name>.spec.ts`
- `python3 scripts/tests.py run --spec <name>.spec.ts --detach`
- `node frontend/apps/web_app/scripts/visual-smoke.mjs --url https://app.dev.openmates.org/<route> --session <id>`
- `python3 scripts/sessions.py visual-smoke --session <id> --url https://app.dev.openmates.org/<route> --viewport laptop --viewport mobile --result passed --method playwright --run-id test-results/visual-smoke/<run>/summary.json --summary "Reviewed laptop and mobile screenshots. Defects: none. Accepted differences: none."`
- `python3 scripts/sessions.py deploy --session <id> --title "..." --message "..."`
