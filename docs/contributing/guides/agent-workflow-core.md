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
For hook, worktree, or child-chat debugging, read or search existing OpenCode
chats with `python3 scripts/sessions.py chat read <ses_or_url>` and
`python3 scripts/sessions.py chat search <ses_or_url> "query"`.

Before editing, discover the relevant files, source patterns, docs, and tests.
Use the smallest correct change. Prefer deterministic audits or focused tests
when repeated mistakes, flaky behavior, safety risks, or workflow drift are
found.

Whenever asking a clarifying question, include an explicit `Recommendation:`
with the evidence-based preferred answer and brief rationale, plus `Examples:`
with concrete, task-specific options or outcomes. Ask only one decision question
per message; the recommendation and examples are supporting context, not extra
questions. If evidence is incomplete, recommend the safest reversible default
and state the uncertainty.

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
completion gate. If any reviewed frame shows an objective product defect such as
clipping, premature truncation, wrong metadata, raw protocol/error text, missing
processing animation, stale loading state, or broken navigation, classify it as
an implementation defect and automatically return to a failing test, product
fix, deploy, source rerun, and replacement recording. Do not accept, document as
an accepted difference, or narrate around an obvious rendering defect. Audio
narration remains optional unless explicitly requested.

## Agent Workflow Retrospective

For every non-trivial task-closing summary, include a concise retrospective about the agentic process used to fulfill the request, not about the request's product results. Report only observed preventable process problems from the main chat, research, tool use, delegated agents, and sub-chats, such as failed or redundant searches, incorrect skill or agent selection, instruction conflicts, avoidable rereads or tool calls, policy or hook friction, abandoned approaches, missed verification, or coordination failures. Do not repeat implementation results, changed files, discovered product bugs, test outcomes, or remaining product work unless an agent-workflow deficiency caused or unnecessarily prolonged them. Ordinary task difficulty is not a workflow issue.

For each observed preventable process problem, check the relevant existing hooks, skills, agents, agent instructions, and deterministic audits/tests before recommending the smallest concrete workflow improvement. Classify each recommendation as a hook, skill, agent/subagent definition, agent instruction, or deterministic audit/test. Do not recommend new prompt prose when an existing mechanism already covers the issue or a deterministic guard would be more reliable. State when existing coverage is sufficient and no change is warranted. Use `None observed` when no preventable agent-workflow issue occurred. Do not invent problems, expose hidden reasoning, guess durations, or include raw private logs or private chat content. Simple requests, clarification-only turns, and progress updates do not require this section.

## Common Commands

- `python3 scripts/sync_agent_parity.py --check`
- `python3 scripts/audit_opencode_output_quality.py`
- `python3 scripts/audit_agent_tooling_parity.py`
- `python3 scripts/tests.py run --spec <name>.spec.ts`
- `python3 scripts/tests.py run --spec <name>.spec.ts --detach`
- `python3 scripts/sessions.py chat read <ses_or_code_dev_url>`
- `python3 scripts/sessions.py chat search <ses_or_code_dev_url> "worktree"`
- `node frontend/apps/web_app/scripts/visual-smoke.mjs --url https://app.dev.openmates.org/<route> --session <id>`
- `python3 scripts/sessions.py visual-smoke --session <id> --url https://app.dev.openmates.org/<route> --viewport laptop --viewport mobile --result passed --method playwright --run-id test-results/visual-smoke/<run>/summary.json --summary "Reviewed laptop and mobile screenshots. Defects: none. Accepted differences: none."`
- `python3 scripts/sessions.py deploy --session <id> --title "..." --message "..."`
