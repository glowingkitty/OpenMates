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

For private OpenMatesCloud overlay work, keep OpenMates as the control-plane
project but start the session with `python3 scripts/sessions.py start --repo
openmatescloud --mode <mode> --task "..."`. The OpenCode hooks route normal
file and shell tools into the sibling `/home/superdev/projects/OpenMatesCloud`
checkout, while `python3 scripts/sessions.py deploy --session <id> ...` stays
on the control plane and commits/pushes only the tracked OpenMatesCloud files to
`origin/main`. Do not use raw `git commit` or `git push` in the sibling repo.

When the user attaches files or images to an OpenCode chat, they are retained in
the local OpenCode SQLite database as chat file parts. `sessions.py start`
prints an `OPENCODE ATTACHMENTS` box when the current chat has extractable
uploads. Extract them with
`python3 scripts/sessions.py chat attachments <ses_or_url> --out /tmp/opencode/<task>-attachments`
before substituting a regenerated screenshot or asking the user to resend the
file.

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
When checking deployed-code readiness from a session worktree that lacks
`frontend/apps/web_app/.vercel/project.json`, prefer the same `scripts/tests.py`
`--gate-deploy --expected-commit <sha>` path instead of retrying Vercel helper
commands that require local Vercel metadata.
For browser inspection or visual-smoke screenshots from a dependency-light
session worktree, use
`python3 scripts/playwright_visual_smoke.py --url <url> --session <id>` or the
existing Node wrapper; it falls back to the Python helper when local
`node_modules` are absent. Do not run `python3 -m playwright install chromium`
unless the helper reports that no global browser executable is available and the
user has approved the large browser download.

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

Every new feature implementation, every new hardcoded example chat, and every
nightly/daily/CI failed E2E that is actively debugged in a chat and turns green
requires proof-video evidence before completion. A test report, screenshots, or
visual-smoke evidence alone never satisfies this gate. Use `create-demo-video`
with passing real CLI or deployed Playwright evidence, ElevenLabs
`eleven_flash_v2_5` narration audio, and burned-in captions. Web/spec/example
chat proof uses separate phone and laptop videos, Apple proof uses separate
iPhone portrait and iPad landscape videos, and CLI proof uses one terminal video.
Use exact device-profile dimensions: phone web `390x844`, laptop web `1440x900`,
iPhone portrait `393x852`, iPad landscape `1366x1024`, and CLI terminal
`1280x720`. Do not accept black bars, letterboxing, pillarboxing, or device
captures wrapped in a generic 16:9/16:10 canvas. Narration must describe the
specific visible UI/action/result, not generic success claims; use retiming or a
last-frame hold when the source flow moves too quickly, and mix product audio
under narration when playback is part of the claim. Give the active agent the
canonical narration and bounded image frames, never the full video. Use a default
three-second interval plus event boundaries, request exact-timestamp frames only
when needed, and require confirmed Discord delivery before completion when the
proof destination is configured. If any reviewed frame shows an objective product
defect such as clipping, premature truncation, wrong metadata, raw protocol/error
text, missing processing animation, stale loading state, or broken navigation,
classify it as an implementation defect and automatically return to a failing
test, product fix, deploy, source rerun, and replacement recording. Do not
accept, document as an accepted difference, or narrate around an obvious
rendering defect.

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
- `python3 scripts/sessions.py chat attachments <ses_or_code_dev_url> --out /tmp/opencode/<task>-attachments`
- `python3 scripts/playwright_visual_smoke.py --url https://app.dev.openmates.org/<route> --session <id>`
- `node frontend/apps/web_app/scripts/visual-smoke.mjs --url https://app.dev.openmates.org/<route> --session <id>`
- `python3 scripts/sessions.py visual-smoke --session <id> --url https://app.dev.openmates.org/<route> --viewport laptop --viewport mobile --result passed --method playwright --run-id test-results/visual-smoke/<run>/summary.json --summary "Reviewed laptop and mobile screenshots. Defects: none. Accepted differences: none."`
- `python3 scripts/sessions.py deploy --session <id> --title "..." --message "..."`
