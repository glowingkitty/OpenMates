# Agent Workflow Core

OpenCode is the primary OpenMates coding runtime. Claude Code remains the
canonical authoring source for project skills, subagents, hooks, and shared
rules; Codex and OpenCode consume generated or bridged mirrors.

Each top-level OpenCode chat owns at most one physical source worktree per
repository. Repeated starts and post-deploy continuation reuse that worktree;
temporary integration worktrees exist only for the bounded deploy operation.
OpenCode Web itself is stopped and started only inside the existing Zellij
`code` session through `scripts/start-opencode-server.sh`, never through a
detached process or systemd unit.

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

To embed generated images, videos, or PDFs in an OpenCode assistant response, upload the
media with `python3 scripts/opencode_response_media.py <path> --alt "..."` and
paste the returned Markdown or HTML snippet. The script stores plaintext media in
a private Hetzner S3 bucket with 48-hour object expiry and a 48-hour presigned URL.
Use only intentionally shareable screenshots, diagrams, or demo clips; do not use
it for secrets, private user data, logs, raw production evidence, or durable docs.
For the raw video from every `*.spec.ts` run and every real OpenMates CLI E2E
run, use the helper's `--latest-run-type` path through `scripts/tests.py run` or
`scripts/cli_video_capture.py`, then paste the emitted `<video>` HTML in the next
assistant progress response after the tool returns. This is required even when
the run failed, the proof is visually broken, or more debugging is still needed,
because the operator needs to see visual progress over time. These run-type
uploads use content-addressed S3 keys under `opencode-responses/runs/`, so an
artifact embedded in an earlier response cannot be replaced by a later run.
Every implemented executable spec requires its success response to include the
delivered `snippet_html` for every required CLI, web, and native proof video in
that same task-closing response. Do not replace embedded `<video>` elements with
artifact paths, links, screenshots, or prose saying the proof was produced.
External video playback also requires the OpenCode Web CSP to allow `media-src https:`.
When a screenshot or short clip materially helps the user understand a visual UI
state, bug fix, visual-smoke result, proof-video, or implementation defect,
include the uploaded media directly in the chat response instead of only naming
an artifact path.
When a proof-video review, visual smoke, or media validation fails and the script
output includes `image_upload_command`, run it and embed the returned image
Markdown in the blocker response. The image is required even when a video upload
command is also available, so OpenCode can show the defect immediately.

Before asking for approval for a new or modified Contract, run
`python3 scripts/sessions.py contract approval-pdf --session <session-id> --bundle <bundle> --baseline-ref HEAD`
and paste the returned PDF Markdown link into the same response. The routed
wrapper uses the current approval tooling and binds the PDF to the
exact bundle fingerprint and includes the complete Contract plus examples. Only
changed text is colored: inline green `+` insertions, inline red `-` deletions,
and neutral unchanged text. A fingerprint, summary, raw local path, or unlinked
claim that a PDF exists is not sufficient. Repair rendering or upload before
asking for approval. The renderer also writes a JSON review artifact. After
explicit approval, pass that artifact to `scripts/contracts.py approve
--review-artifact <path>` so approval cannot race ahead to a different Contract
fingerprint or PDF.

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

For TypeScript validation in a dependency-light CLI worktree, do not install or
repair packages inside that chat. Preview the exact file set with
`sessions.py prepare-deploy --session <id> --only <paths...>`, then run
`sessions.py verify-prepared --session <id> --profile cli-typecheck --only
<paths...> --expected-manifest-id <manifest>`. Use `cli-storage-unit` for the
focused storage regression. The verifier applies only that immutable patch to a
disposable checkout and reuses the canonical dependency tree only when its
`pnpm-lock.yaml` hash matches exactly. Inspect the active global CLI without
reinstalling it with the `installed-cli-identity` profile; a version label alone
is not proof that the executable contains candidate source.

OpenCode records response video snippets and Figma exports as pending local
delivery artifacts. The next completed progress response must contain the exact
video/image snippet; if the response is interrupted or compacted, the hook may
issue at most two operation-scoped delivery prompts. This does not authorize a
generic idle continuation or rerunning a completed test. Pending media delivery
is acknowledged only after the assistant response visibly contains the snippet.

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
Before a success final for executable-spec work, run `python3 scripts/spec_verify.py
<spec> --phase complete --json`, require `complete: true`, and paste every delivered
proof-video `snippet_html` verbatim into the response.

When a final answer needs more than one sentence, use a scan-first layout. Start
with one state heading: `## ✅ Done`, `## 🚧 Blocked`, `## ❓ Decision Needed`, or
`## 🧠 Investigation`. Prefer compact tables for files, tests, blockers, risks,
and next actions; use short bullets only when a table would be awkward. Keep
narrative paragraphs under three lines. Use icons semantically and sparingly:
`📁` files, `🧪` verification, `⚠️` risk or uncertainty, `➡️` next action, and
`🔧` fix. Do not paste large YAML, JSON, contracts, or logs into blocker
summaries unless the user asks; reference the path or hash and provide one
copy-paste action when useful.

Every new feature implementation, every new hardcoded example chat, and every
nightly/daily/CI failed E2E that is actively debugged in a chat and turns green
requires proof-video evidence before completion. A test report, screenshots, or
visual-smoke evidence alone never satisfies this gate. Use `create-demo-video`
and `python3 scripts/proof_video_workflow.py start --current --spec <name>.spec.ts`
with passing deployed Playwright, Apple, or real OpenMates CLI evidence and
device-scoped, hash-bound WebVTT captions that are toggleable in the player and never reduce or obscure the clean frame; narration audio is optional. Web/spec/example chat proof uses
separate phone and laptop videos, Apple proof uses separate iPhone portrait and
iPad landscape videos, and CLI proof uses one terminal video only for the actual `openmates` CLI product surface being demonstrated or fixed. Do not ask for CLI proof videos for generic smoke scripts, pytest helpers, Node scripts, or shell wrappers that do not visibly execute the OpenMates CLI.
Use exact device-profile dimensions: phone web `390x844`, laptop web `1440x900`,
iPhone portrait `393x852`, iPad landscape `1366x1024`, and CLI terminal
`1280x720`. Do not accept black bars, letterboxing, pillarboxing, or device
captures wrapped in a generic 16:9/16:10 canvas. The transcript must describe the
specific visible UI/action/result, not generic success claims. For proof-enabled
Playwright specs, the committed `*.spec.ts` file is the source of truth for the
browser or terminal recording contract: command, profile, assertions, transcript,
checkpoints, and attachments must come from the spec rather than a chat-only
override. Use retiming or a last-frame hold when the source flow moves too quickly,
and preserve product audio when playback is part of the claim. Do not ask the user
for separate proof-contract approval before rendering; the tooling authorizes the
canonical contract from the spec/test assertions. Give the active agent the canonical transcript
and bounded image frames, never the full video. Use a default three-second
interval plus event boundaries, request exact-timestamp frames only when needed,
then upload the approved proof media with `scripts/opencode_response_media.py`.
The reviewer must complete an explicit quality scan for every frame before
evaluating assertions; an empty incidental-finding list is not evidence that the
scan happened. Every frame must be checked for layout, readability, geometry,
controls, visual assets, application state, consistency, and proof alignment.
When review fails, the workflow emits a representative blocker frame image and
`image_upload_command`; upload and embed that image in the blocker response before
asking for user input or pausing.
Do not ask a visual-intent question until the exact cited image is visibly embedded
in the same response with concise context explaining what to inspect and why a
decision is needed. If upload or rendering fails, repair or retry media delivery
first; a text-only question, local path, or uncited description is not an acceptable
fallback.
This is the OpenCode response-media proof path: embed the returned image Markdown
or `<video>` HTML directly in the final OpenCode response. Do not send proof media
to Discord unless the user explicitly asks for a separate Discord mirror. If any reviewed frame shows an objective product
defect such as clipping, premature truncation, wrong metadata, raw protocol/error
text, missing processing animation, stale loading state, or broken navigation,
classify it as an implementation defect and automatically return to a failing
test, product fix, deploy, source rerun, and replacement recording. Do not
accept, document as an accepted difference, or narrate around an obvious
rendering defect.
If the visible concern could plausibly be intentional design, classify its intent
as unclear, upload the representative blocker frame, and ask the user for consent
before changing product code. Do not automatically repair subjective or ambiguous
visual differences.

## Agent Workflow Retrospective

For every non-trivial task-closing summary, include a concise retrospective about the agentic process used to fulfill the request, not about the request's product results. Report only observed preventable process problems and inefficiencies from the main chat, research, tool use, delegated agents, and sub-chats, such as failed or redundant searches, incorrect skill or agent selection, instruction conflicts, avoidable rereads or tool calls, unnecessary retries, avoidable context growth, wasted subagent runs, policy or hook friction, abandoned approaches, missed verification, or coordination failures. Include only inefficiencies that wasted agent cycles, context, tool calls, subagent runs, retries, or inference tokens and could plausibly have been prevented by better deterministic scripts, hooks, focused audits/tests, skills, agent/subagent definitions, or runtime instructions. Do not repeat implementation results, changed files, discovered product bugs, test outcomes, or remaining product work unless an agent-workflow deficiency caused or unnecessarily prolonged them. Ordinary task difficulty is not a workflow issue.

For each observed preventable process problem or inefficiency, check the relevant existing hooks, skills, agents, agent instructions, and deterministic audits/tests before recommending the smallest concrete workflow improvement. Classify each recommendation as a hook, skill, agent/subagent definition, agent instruction, or deterministic audit/test. Do not recommend new prompt prose when an existing mechanism already covers the issue or a deterministic guard would be more reliable. Ground efficiency claims in observable actions only; do not estimate token counts or durations. State when existing coverage is sufficient and no change is warranted. Use `None observed` when no preventable agent-workflow issue occurred. Do not invent problems, expose hidden reasoning, guess durations, or include raw private logs or private chat content. Simple requests, clarification-only turns, and progress updates do not require this section.

## Common Commands

- `python3 scripts/sync_agent_parity.py --check`
- `python3 scripts/audit_opencode_output_quality.py`
- `python3 scripts/audit_agent_tooling_parity.py`
- `python3 scripts/tests.py run --spec <name>.spec.ts`
- `python3 scripts/tests.py run --spec <name>.spec.ts --detach`
- `python3 scripts/sessions.py chat read <ses_or_code_dev_url>`
- `python3 scripts/sessions.py chat search <ses_or_code_dev_url> "worktree"`
- `python3 scripts/sessions.py chat attachments <ses_or_code_dev_url> --out /tmp/opencode/<task>-attachments`
- `python3 scripts/opencode_response_media.py <path> --alt "Description"`
- `python3 scripts/playwright_visual_smoke.py --url https://app.dev.openmates.org/<route> --session <id>`
- `node frontend/apps/web_app/scripts/visual-smoke.mjs --url https://app.dev.openmates.org/<route> --session <id>`
- `python3 scripts/sessions.py visual-smoke --session <id> --url https://app.dev.openmates.org/<route> --viewport laptop --viewport mobile --result passed --method playwright --run-id test-results/visual-smoke/<run>/summary.json --summary "Reviewed laptop and mobile screenshots. Defects: none. Accepted differences: none."`
- `python3 scripts/sessions.py deploy --session <id> --title "..." --message "..."`
